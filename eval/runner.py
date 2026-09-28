"""评测运行器：在自建数据集上真实测量规则层与「规则 + 语义层」的表现。

一条命令跑完：

    make eval
    # 等价于
    .venv/bin/python -m eval.runner --mode both --out eval/results

输出：
- ``eval/results/report.json``   机器可读的完整结果（供 eval.gate 做门禁）
- ``eval/results/summary.md``    人读的对照表（贴进 docs/eval-report.md）
- ``eval/results/predictions.jsonl``  每条样本的判定明细（失败案例分析用）

设计说明：
- 默认**进程内**直接调用 ``service.scanner.Scanner``（与 ``POST /scan`` 同一份代码路径），
  省掉 HTTP 往返、也让指标不受服务进程状态影响；需要验证服务链路时用 ``--endpoint``。
- 语义层非确定性：本项目把温度设为 0 并记录 prompt 版本；报告里如实说明非确定性未消除。
- 支持 ``--resume``：把逐条结果落到 ``checkpoint.jsonl``，网络中断后接着跑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.metrics import Confusion, confusion  # noqa: E402

DEFAULT_DATASET = REPO_ROOT / "eval" / "dataset" / "heldout.jsonl"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dataset(path: Path) -> list[dict]:
    items: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"数据集第 {lineno} 行不是合法 JSON：{exc}") from exc
            for field in ("id", "text", "label", "category"):
                if field not in obj:
                    raise SystemExit(f"数据集第 {lineno} 行缺少字段 {field!r}")
            if obj["label"] not in (0, 1):
                raise SystemExit(f"数据集第 {lineno} 行 label 非法：{obj['label']!r}")
            items.append(obj)
    if not items:
        raise SystemExit(f"数据集为空：{path}")
    return items


# --------------------------------------------------------------------------- #
# 扫描后端
# --------------------------------------------------------------------------- #
class InProcessBackend:
    """直接调用 Scanner（与 /scan 同一实现）。"""

    name = "in-process"

    def __init__(self, mode: str) -> None:
        from service.scanner import Scanner

        self.mode = mode
        self.scanner = Scanner()
        if "semantic" in mode and not self.scanner.semantic_enabled:
            raise SystemExit("语义评测需要 DEEPSEEK_API_KEY；服务可降级，但不能将无模型调用作为双层评测。")

    def scan(self, text: str) -> dict:
        result = self.scanner.scan(text, mode=self.mode)
        hits = [d.risk_type for d in result.detections if d.is_risky]
        return {
            "risky": result.risky,
            "hits": hits,
            "semantic_enabled": self.scanner.semantic_enabled,
            "detections": [d.__dict__ for d in result.detections],
        }

    def teardown(self) -> dict:
        client = self.scanner.semantic_client
        return client.stats.to_dict() if client else {}


class HttpBackend:
    """通过 HTTP 调 ``POST /scan``（验证服务链路时使用）。"""

    name = "http"

    def __init__(self, mode: str, endpoint: str) -> None:
        import httpx

        self.mode = mode
        self.endpoint = endpoint.rstrip("/")
        self.client = httpx.Client(timeout=120)

    def scan(self, text: str) -> dict:
        resp = self.client.post(
            f"{self.endpoint}/scan", params={"mode": self.mode}, json={"text": text}
        )
        resp.raise_for_status()
        data = resp.json()
        hits = [d["risk_type"] for d in data["detections"] if d["is_risky"]]
        return {"risky": data["risky"], "hits": hits, "semantic_enabled": None, "detections": data["detections"]}

    def teardown(self) -> dict:
        try:
            resp = self.client.get(f"{self.endpoint}/health")
            return resp.json().get("semantic_stats", {})
        except Exception:  # noqa: BLE001
            return {}
        finally:
            self.client.close()


# --------------------------------------------------------------------------- #
# 评测主流程
# --------------------------------------------------------------------------- #
def run_mode(
    mode: str,
    dataset: list[dict],
    backend_kind: str,
    endpoint: str,
    checkpoint: Path | None,
    verbose: bool,
) -> dict:
    backend = InProcessBackend(mode) if backend_kind == "in-process" else HttpBackend(mode, endpoint)

    done: dict[str, dict] = {}
    if checkpoint and checkpoint.exists():
        with checkpoint.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rec = json.loads(line)
                    done[rec["id"]] = rec
        print(f"  [resume] 复用 {len(done)} 条已完成记录", file=sys.stderr)

    if checkpoint:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
    ck_fh = checkpoint.open("a", encoding="utf-8") if checkpoint else None

    predictions: list[dict] = []
    latencies: list[float] = []
    try:
        for i, item in enumerate(dataset, 1):
            if item["id"] in done:
                predictions.append(done[item["id"]])
                continue
            started = time.monotonic()
            try:
                out = backend.scan(item["text"])
                error = None
            except Exception as exc:  # noqa: BLE001 - 单条失败不能让整轮评测崩掉
                out = {"risky": False, "hits": [], "detections": []}
                error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = (time.monotonic() - started) * 1000
            latencies.append(elapsed_ms)

            rec = {
                "id": item["id"],
                "category": item["category"],
                "label": item["label"],
                "pred": 1 if out["risky"] else 0,
                "hits": out["hits"],
                "latency_ms": round(elapsed_ms, 1),
                "error": error,
                "text_preview": item["text"][:120],
            }
            predictions.append(rec)
            done[item["id"]] = rec
            if ck_fh:
                ck_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ck_fh.flush()
            if verbose:
                flag = "OK " if rec["pred"] == rec["label"] else "MISS"
                print(f"  [{i}/{len(dataset)}] {flag} {rec['id']:<12} pred={rec['pred']} {rec['hits']}", file=sys.stderr)
    finally:
        if ck_fh:
            ck_fh.close()

    overall = confusion([(p["label"], p["pred"]) for p in predictions])

    by_category: dict[str, dict] = {}
    for cat in sorted({p["category"] for p in predictions}):
        # 分类别口径：只看"针对该类别"的样本（恶意样本 = 该攻击类型；正常样本 = 该类检测器的负样本）
        subset = [p for p in predictions if p["category"] == cat]
        conf = confusion([(p["label"], p["pred"]) for p in subset])
        by_category[cat] = conf.to_dict()

    # 恶意样本按"哪一类攻击"切分召回；正常样本按"针对哪个检测器"切分误报
    malicious = [p for p in predictions if p["label"] == 1]
    benign = [p for p in predictions if p["label"] == 0]
    recall_by_attack = {
        cat: confusion([(p["label"], p["pred"]) for p in malicious if p["category"] == cat]).to_dict()
        for cat in sorted({p["category"] for p in malicious})
    }
    fpr_by_probe = {
        cat: confusion([(p["label"], p["pred"]) for p in benign if p["category"] == cat]).to_dict()
        for cat in sorted({p["category"] for p in benign})
    }

    errors = [p for p in predictions if p["error"]]
    result = {
        "mode": mode,
        "backend": backend.name,
        "overall": overall.to_dict(),
        "by_category": by_category,
        "recall_by_attack": recall_by_attack,
        "fpr_by_probe": fpr_by_probe,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "p50": round(statistics.median(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "errors": {"count": len(errors), "samples": errors[:5]},
        "semantic_stats": backend.teardown(),
        "failures": [
            {"id": p["id"], "category": p["category"], "label": p["label"], "pred": p["pred"], "hits": p["hits"], "text_preview": p["text_preview"]}
            for p in predictions
            if p["pred"] != p["label"]
        ],
        "predictions": predictions,
    }

    # 系统性故障必须"响亮地失败"，绝不能安静地产出一张全 0 的指标表。
    # （真实教训：曾因为模式名笔误导致每条样本都抛 ValueError，被逐条 except 吞掉，
    #   最终报告出现 precision=n/a / recall=0.0000 —— 一个看起来"跑过了"的假结果。）
    if errors and len(errors) >= max(5, int(0.2 * len(predictions))):
        detail = errors[0]["error"]
        raise SystemExit(
            f"模式 {mode} 有 {len(errors)}/{len(predictions)} 条样本执行失败，"
            f"属于系统性故障，已中止（不做指标结论）。首条错误：{detail}"
        )
    return result


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def render_summary(meta: dict, results: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("# 评测结果（由 `make eval` 生成，勿手工编辑）\n")
    lines.append(f"- 生成时间（UTC）：{meta['created_at']}")
    lines.append(f"- 数据集：`{meta['dataset']['path']}`")
    lines.append(f"  - sha256：`{meta['dataset']['sha256']}`")
    lines.append(f"  - 条数：{meta['dataset']['total']}（恶意 {meta['dataset']['malicious']} / 正常 {meta['dataset']['benign']}）")
    lines.append(f"- 运行环境：{meta['environment']['python']} / {meta['environment']['platform']}")
    lines.append(f"- 扫描后端：{meta['backend']}；判定口径：任一层命中即 risky")
    lines.append(f"- prompt 版本：{meta['prompt_version']}\n")

    lines.append("## 数据集构成\n")
    lines.append("| 类别 | 恶意条数 | 正常条数 |")
    lines.append("| --- | --- | --- |")
    for cat in sorted(meta["dataset"]["by_category"]):
        entry = meta["dataset"]["by_category"][cat]
        lines.append(f"| {cat} | {entry['malicious']} | {entry['benign']} |")
    lines.append("")

    lines.append("## 总体指标\n")
    lines.append("| 配置 | TP | FP | FN | TN | precision | recall | F1 | FPR | 准确率 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for mode, res in results.items():
        o = res["overall"]
        lines.append(
            f"| {mode} | {o['tp']} | {o['fp']} | {o['fn']} | {o['tn']} | "
            f"{_fmt(o['precision'])} | {_fmt(o['recall'])} | {_fmt(o['f1'])} | {_fmt(o['fpr'])} | {_fmt(o['accuracy'])} |"
        )
    lines.append("")

    for mode, res in results.items():
        lines.append(f"## 分类别指标 · {mode}\n")
        lines.append("| 类别 | n | TP | FP | FN | TN | precision | recall | F1 | FPR |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for cat, c in res["by_category"].items():
            lines.append(
                f"| {cat} | {c['n']} | {c['tp']} | {c['fp']} | {c['fn']} | {c['tn']} | "
                f"{_fmt(c['precision'])} | {_fmt(c['recall'])} | {_fmt(c['f1'])} | {_fmt(c['fpr'])} |"
            )
        lines.append("")

        stats = res.get("semantic_stats") or {}
        if stats:
            lines.append(f"- 模型：requested={stats.get('requested_model')} / reported={stats.get('reported_model')}")
            lines.append(
                f"- 语义层调用：{stats.get('calls')} 次（成功 {stats.get('ok')} / 失败 {stats.get('failed')} / "
                f"解析失败 {stats.get('parse_failed')}）；失败率 {stats.get('failure_rate')}；"
                f"延迟 p50 {stats.get('latency_ms_p50')} ms / p95 {stats.get('latency_ms_p95')} ms；"
                f"tokens：prompt {stats.get('prompt_tokens')} + completion {stats.get('completion_tokens')}"
            )
            lines.append("")

        lines.append(f"- 平均单条延迟：{res['latency_ms']['mean']} ms（p50 {res['latency_ms']['p50']} / max {res['latency_ms']['max']}）")
        lines.append(f"- 判错条数：{len(res['failures'])}（详见 `predictions.jsonl` 与 report.json 的 `failures` 字段）\n")

    if len(results) > 1:
        modes = list(results)
        base, enhanced = modes[0], modes[-1]
        b, e = results[base]["overall"], results[enhanced]["overall"]
        lines.append("## 对照增量（%s → %s）\n" % (base, enhanced))
        lines.append("| 指标 | %s | %s | 增量 |" % (base, enhanced))
        lines.append("| --- | --- | --- | --- |")
        for key in ("precision", "recall", "f1", "fpr"):
            bv, ev = b[key], e[key]
            delta = "n/a" if bv is None or ev is None else f"{ev - bv:+.4f}"
            lines.append(f"| {key} | {_fmt(bv)} | {_fmt(ev)} | {delta} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def summarize_dataset(dataset: list[dict]) -> dict:
    by_cat: dict[str, dict[str, int]] = {}
    for item in dataset:
        entry = by_cat.setdefault(item["category"], {"malicious": 0, "benign": 0})
        entry["malicious" if item["label"] == 1 else "benign"] += 1
    return {
        "total": len(dataset),
        "malicious": sum(1 for d in dataset if d["label"] == 1),
        "benign": sum(1 for d in dataset if d["label"] == 0),
        "by_category": by_cat,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Guard 评测运行器")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "eval" / "results")
    parser.add_argument(
        "--mode",
        default="both",
        choices=["rules", "rules+semantic", "semantic", "semantic+exfil", "rules+semantic+exfil", "both", "all"],
        help="both = rules 与 rules+semantic；all = 再加上 semantic+exfil（默认 both）",
    )
    parser.add_argument("--backend", default="in-process", choices=["in-process", "http"])
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000", help="--backend http 时的服务地址")
    parser.add_argument("--resume", action="store_true", help="复用 .checkpoint-<mode>.jsonl")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.resume and args.mode != "rules":
        raise SystemExit("语义评测暂不支持 resume：旧检查点缺少可核验的模型与调用统计，请重新完整运行。")

    if not args.dataset.exists():
        raise SystemExit(f"数据集不存在：{args.dataset}")

    dataset = load_dataset(args.dataset)
    # 模式顺序固定为"由弱到强"，让 summary.md 的对照表读起来就是一条递进线
    mode_sets = {
        "both": ["rules", "rules+semantic"],
        "all": ["rules", "rules+semantic", "rules+semantic+exfil"],
    }
    modes = mode_sets.get(args.mode, [args.mode])
    from service.detectors.semantic import PROMPT_VERSION

    try:
        import fastapi
        import httpx

        env_versions = {"fastapi": fastapi.__version__, "httpx": httpx.__version__}
    except Exception:  # noqa: BLE001
        env_versions = {}

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {
            "path": str(args.dataset.relative_to(REPO_ROOT)) if args.dataset.is_relative_to(REPO_ROOT) else str(args.dataset),
            "sha256": sha256_file(args.dataset),
            **summarize_dataset(dataset),
        },
        "environment": {
            "python": f"{platform.python_version()} ({platform.python_implementation()})",
            "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
            **env_versions,
        },
        "backend": args.backend,
        "prompt_version": PROMPT_VERSION,
    }

    results: dict[str, dict] = {}
    args.out.mkdir(parents=True, exist_ok=True)
    for mode in modes:
        print(f"== 运行模式：{mode} ==", file=sys.stderr)
        checkpoint = args.out / f".checkpoint-{mode.replace('+', '_')}.jsonl"
        if not args.resume and checkpoint.exists():
            checkpoint.unlink()
        results[mode] = run_mode(
            mode,
            dataset,
            args.backend,
            args.endpoint,
            checkpoint,
            args.verbose,
        )
        o = results[mode]["overall"]
        print(
            f"   -> precision={_fmt(o['precision'])} recall={_fmt(o['recall'])} "
            f"F1={_fmt(o['f1'])} FPR={_fmt(o['fpr'])}",
            file=sys.stderr,
        )
        # 防"静默降级"：语义层模式下若一次模型调用都没发生，指标不可能是真的
        if "semantic" in mode and not (results[mode].get("semantic_stats") or {}).get("calls"):
            raise SystemExit("语义层调用次数为 0，拒绝生成双层评测结论。")

    report = {"meta": meta, "results": results}
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "summary.md").write_text(render_summary(meta, results), encoding="utf-8")

    # predictions.jsonl：合并所有模式的逐条明细，便于失败案例复盘
    with (args.out / "predictions.jsonl").open("w", encoding="utf-8") as fh:
        for mode, res in results.items():
            for pred in res["predictions"]:
                fh.write(json.dumps({"mode": mode, **pred}, ensure_ascii=False) + "\n")

    print((args.out / "summary.md").read_text(encoding="utf-8"))
    print(f"报告已写入 {args.out}/report.json 与 {args.out}/summary.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
