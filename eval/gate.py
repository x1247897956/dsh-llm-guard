"""评测门禁：把 ``make eval`` 的结果与基线比对，掉线即退出码 1（CI 用）。

用法：

    .venv/bin/python -m eval.gate --results eval/results --baseline eval/baseline.json

判定规则：
- 对 ``baseline.json`` 里声明的每个 ``mode.metric``：
  - 方向为 ``min`` 的指标（precision / recall / f1）：``actual >= threshold - tolerance``
  - 方向为 ``max`` 的指标（fpr）：``actual <= threshold + tolerance``
  - 指标为 ``null``（分母为 0）：**直接判失败**，不允许用"没样本"蒙混过关
- 额外硬性检查：语义层启用时调用失败率不得超过 ``max_semantic_failure_rate``
- 任何一项不达标 → 打印明细并返回 1

``tolerance`` 的存在是因为语义层非确定性；它把门禁做成"掉线拦截"而不是"逐位相等"。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DIRECTION = {"precision": "min", "recall": "min", "f1": "min", "fpr": "max"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(results_dir: Path, baseline_path: Path) -> int:
    report_path = results_dir / "report.json"
    if not report_path.exists():
        print(f"FAIL: 找不到评测结果 {report_path}，请先运行 `make eval`")
        return 1
    if not baseline_path.exists():
        print(f"FAIL: 找不到基线文件 {baseline_path}")
        return 1

    report = load_json(report_path)
    baseline = load_json(baseline_path)
    tolerance = float(baseline.get("tolerance", 0.0))
    results = report.get("results", {})

    print("== LLM Guard 评测门禁 ==")
    print(f"结果文件：{report_path}")
    print(f"基线文件：{baseline_path}（tolerance={tolerance}）")
    print(f"数据集 sha256：{report['meta']['dataset']['sha256']}\n")

    failures: list[str] = []
    for mode, spec in baseline.get("metrics", {}).items():
        if mode not in results:
            failures.append(f"缺少模式 {mode} 的结果（baseline 要求，请用 --mode both 跑）")
            print(f"FAIL: 结果里没有模式 {mode}")
            continue
        actual = results[mode]["overall"]
        print(f"-- 模式 {mode} --")
        for metric, threshold in spec.items():
            direction = DIRECTION.get(metric, "min")
            value = actual.get(metric)
            if value is None:
                failures.append(f"{mode}.{metric} 为 null（分母为 0）")
                print(f"  FAIL {metric}: null（分母为 0，不允许）")
                continue
            if direction == "min":
                ok = value >= float(threshold) - tolerance
                op = ">="
            else:
                ok = value <= float(threshold) + tolerance
                op = "<="
            print(
                f"  {'PASS' if ok else 'FAIL'} {metric}: 实际 {value:.4f} {op} "
                f"阈值 {threshold} (tolerance {tolerance})"
            )
            if not ok:
                failures.append(f"{mode}.{metric} 实际 {value:.4f}，要求 {op} {threshold}（tolerance {tolerance}）")

    max_fail_rate = baseline.get("max_semantic_failure_rate")
    if max_fail_rate is not None:
        for mode, res in results.items():
            stats = res.get("semantic_stats") or {}
            if not stats.get("calls"):
                continue
            rate = stats.get("failure_rate", 0.0)
            ok = rate <= float(max_fail_rate)
            print(f"-- 语义层可用性 ({mode}) --")
            print(
                f"  {'PASS' if ok else 'FAIL'} failure_rate: {rate} <= {max_fail_rate}"
                f"（calls={stats.get('calls')} failed={stats.get('failed')}）"
            )
            if not ok:
                failures.append(f"{mode} 语义层失败率 {rate} > {max_fail_rate}")

    if failures:
        print("\n门禁未通过，拦截本次变更：")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("\n门禁通过。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM Guard 评测门禁")
    parser.add_argument("--results", type=Path, default=REPO_ROOT / "eval" / "results")
    parser.add_argument("--baseline", type=Path, default=REPO_ROOT / "eval" / "baseline.json")
    args = parser.parse_args(argv)
    return check(args.results, args.baseline)


if __name__ == "__main__":
    sys.exit(main())
