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
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DIRECTION = {"precision": "min", "recall": "min", "f1": "min", "fpr": "max"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def probability(value: object) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= 1)


def check(results_dir: Path, baseline_path: Path) -> int:
    try:
        return _check(results_dir, baseline_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"FAIL: 无效的门禁输入：{exc}")
        return 1


def _check(results_dir: Path, baseline_path: Path) -> int:
    report_path = results_dir / "report.json"
    if not report_path.exists():
        print(f"FAIL: 找不到评测结果 {report_path}，请先运行 `make eval`")
        return 1
    if not baseline_path.exists():
        print(f"FAIL: 找不到基线文件 {baseline_path}")
        return 1

    report = load_json(report_path)
    baseline = load_json(baseline_path)
    tolerance = baseline.get("tolerance", 0.0)
    if not probability(tolerance):
        raise ValueError("tolerance 必须是 0 到 1 的有限数")
    if not baseline.get("metrics"):
        raise ValueError("baseline.metrics 不得为空")
    results = report.get("results", {})

    print("== LLM Guard 评测门禁 ==")
    print(f"结果文件：{report_path}")
    print(f"基线文件：{baseline_path}（tolerance={tolerance}）")
    print(f"数据集 sha256：{report['meta']['dataset']['sha256']}\n")

    failures: list[str] = []
    expected_hash = baseline.get("dataset_sha256")
    if expected_hash is not None and report["meta"]["dataset"]["sha256"] != expected_hash:
        failures.append("数据集 sha256 与基线不一致")
    for mode, spec in baseline.get("metrics", {}).items():
        if mode not in results:
            failures.append(f"缺少模式 {mode} 的结果（baseline 要求，请用 --mode both 跑）")
            print(f"FAIL: 结果里没有模式 {mode}")
            continue
        actual = results[mode]["overall"]
        print(f"-- 模式 {mode} --")
        if not spec:
            failures.append(f"{mode} 的指标配置为空")
        for metric, threshold in spec.items():
            if metric not in DIRECTION or not probability(threshold):
                failures.append(f"无效的指标配置 {mode}.{metric}: {threshold}")
                continue
            direction = DIRECTION[metric]
            value = actual.get(metric)
            if not probability(value):
                failures.append(f"{mode}.{metric} 无效（必须是 0 到 1 的有限数）")
                print(f"  FAIL {metric}: 无效数值 {value!r}")
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
    if max_fail_rate is not None and not probability(max_fail_rate):
        raise ValueError("max_semantic_failure_rate 必须是 0 到 1 的有限数")
    for mode, res in results.items():
        if mode != "rules+semantic":
            continue
        stats = res.get("semantic_stats") or {}
        calls, failed, parse_failed, rate = (stats.get(key) for key in ("calls", "failed", "parse_failed", "failure_rate"))
        if (type(calls) is not int or calls <= 0 or type(failed) is not int
                or type(parse_failed) is not int or min(failed, parse_failed) < 0
                or failed > calls or parse_failed > calls or not probability(rate)):
            failures.append(f"{mode} 语义调用统计无效：必须实际调用且计数、失败率合法")
            continue
        # The runner serializes the rate rounded to four decimal places.
        actual_rate = (failed + parse_failed) / calls
        if not math.isclose(rate, actual_rate, abs_tol=0.000051):
            failures.append(f"{mode} failure_rate 与 failed/calls 不一致")
            continue
        if max_fail_rate is not None:
            ok = actual_rate <= max_fail_rate
            print(f"-- 语义层可用性 ({mode}) --")
            print(f"  {'PASS' if ok else 'FAIL'} failure_rate: {actual_rate:.4f} "
                  f"<= {max_fail_rate}（calls={calls} failed={failed}）")
            if not ok:
                failures.append(f"{mode} 语义层失败率 {actual_rate} > {max_fail_rate}")

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
