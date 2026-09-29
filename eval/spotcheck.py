"""生成盲审表并将用户填入的标签与可信数据集及预测按 ID 合并评分。

程序不会填写人工标签。`human_label` 留空直到人工完成复核；评分时标签必须是 0 或 1。

工作流：

    python -m eval.spotcheck sheet  --frac 0.25          # 1) 生成复核表（CSV，含留空列）
    # 人工逐行填 human_label 列 ...
    python -m eval.spotcheck score  --sheet eval/results/spotcheck.csv   # 2) 统计一致率

三种一致率（区分开，别混为一谈）：
- ``label_vs_human``：作者的原始标注 vs 人工复核标注 → 衡量**标注质量**
- ``pred_vs_label``：检测器判定 vs 原始标注（只统计抽到的子集）→ 子集上的机器表现
- ``pred_vs_human``：检测器判定 vs 人工复核标注 → 机器与人工的最终一致率
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "eval" / "dataset" / "heldout.jsonl"
DEFAULT_PREDS = REPO_ROOT / "eval" / "results" / "predictions.jsonl"
DEFAULT_SHEET = REPO_ROOT / "eval" / "results" / "spotcheck.csv"


def _load_predictions(path: Path, mode: str) -> dict[str, dict]:
    """按 id 取该模式的判定（predictions.jsonl 里每个模式各一份）。"""
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("mode") == mode:
                if rec["id"] in out:
                    raise ValueError("duplicate prediction id for selected mode")
                out[rec["id"]] = rec
    return out


def make_sheet(dataset: Path, preds_path: Path, out: Path, mode: str, frac: float, seed: int) -> int:
    if not 0 < frac <= 1:
        raise ValueError("frac must be in (0, 1]")
    rows = list(_load_dataset(dataset).values())

    rng = random.Random(seed)
    # 分层抽样：恶意/正常各按比例抽，保证抽检子集的构成与全集一致
    picked: list[dict] = []
    for label in (1, 0):
        group = [r for r in rows if r["label"] == label]
        k = math.ceil(len(group) * frac)
        picked.extend(rng.sample(group, k))
    picked.sort(key=lambda r: r["id"])

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "id",
                "text",
                "human_label",
                "human_note",
            ]
        )
        for r in picked:
            writer.writerow(
                [
                    r["id"],
                    r["text"],
                    "",  # 待人工填写：1 = 恶意，0 = 正常
                    "",  # 待人工填写：复核理由
                ]
            )

    print(f"复核表已生成：{out}")
    print(f"抽检 {len(picked)} / {len(rows)} 条（frac={frac}, seed={seed}）")
    print("请逐行填写 human_label（1=恶意 / 0=正常）与 human_note，然后运行：")
    print(f"  .venv/bin/python -m eval.spotcheck score --sheet {out}")
    return 0


def _load_dataset(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    out = {r["id"]: r for r in records}
    if not out or len(out) != len(records):
        raise ValueError("dataset must be nonempty and have unique ids")
    if any(type(r["label"]) is not int or r["label"] not in (0, 1) for r in records):
        raise ValueError("dataset labels must be 0 or 1")
    return out


def score_sheet(
    sheet: Path, out_json: Path | None, dataset: Path = DEFAULT_DATASET,
    preds_path: Path = DEFAULT_PREDS, mode: str = "rules+semantic",
) -> int:
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    trusted = _load_dataset(dataset)
    preds = _load_predictions(preds_path, mode)
    seen: set[str] = set()
    filled = []
    for row in rows:
        sid = row.get("id", "")
        if sid in seen or sid not in trusted:
            raise ValueError("sheet contains duplicate or unknown id")
        seen.add(sid)
        if row.get("text") != trusted[sid]["text"]:
            raise ValueError(f"review text differs from dataset: {sid}")
        human = row.get("human_label", "").strip()
        if not human:
            continue
        if human not in ("0", "1"):
            raise ValueError(f"human_label must be 0 or 1: {sid}")
        pred = preds.get(sid, {}).get("pred")
        if type(pred) is not int or pred not in (0, 1):
            raise ValueError(f"missing or invalid prediction: {sid}")
        filled.append({**row, "human_label": int(human),
                       "author_label": trusted[sid]["label"],
                       "category": trusted[sid]["category"], "machine_pred": pred})
    if not filled:
        print(f"FAIL: 复核表 {sheet} 里还没有任何 human_label，先人工填写。")
        return 1

    total = len(filled)
    agree_label = sum(1 for r in filled if int(r["human_label"]) == int(r["author_label"]))
    agree_pred = sum(1 for r in filled if int(r["human_label"]) == int(r["machine_pred"]))
    pred_vs_label = sum(1 for r in filled if int(r["machine_pred"]) == int(r["author_label"]))
    human_pos = sum(1 for r in filled if int(r["human_label"]) == 1)

    # 人工改了标注的样本：这是数据集质量的直接证据，必须列出来
    corrected = [
        {
            "id": r["id"],
            "category": r["category"],
            "author_label": int(r["author_label"]),
            "human_label": int(r["human_label"]),
            "human_note": r.get("human_note", ""),
        }
        for r in filled
        if int(r["human_label"]) != int(r["author_label"])
    ]

    result = {
        "sheet": str(sheet),
        "n_spotchecked": total,
        "n_dataset": len(trusted),
        "n_sheet": len(rows),
        "dataset": str(dataset),
        "predictions": str(preds_path),
        "mode": mode,
        "coverage_requirement_met": total >= math.ceil(0.2 * len(trusted)),
        "spotcheck_frac": round(total / len(trusted), 4),
        "n_human_positive": human_pos,
        "n_human_negative": total - human_pos,
        "agreement_machine_vs_author_label": round(pred_vs_label / total, 4),
        "agreement_human_vs_author_label": round(agree_label / total, 4),
        "agreement_machine_vs_human_label": round(agree_pred / total, 4),
        "n_disagreement_machine_vs_human": total - agree_pred,
        "n_relabeled_by_human": len(corrected),
        "relabeled": corrected,
    }

    print("== 人工抽检结果 ==")
    print(f"复核表：{sheet}")
    print(f"抽检条数：{total} / {len(trusted)}（{result['spotcheck_frac']:.1%}）")
    print(f"人工判定为恶意 {human_pos} / 正常 {total - human_pos}")
    print(f"机器 vs 人工一致率：{result['agreement_machine_vs_human_label']:.4f}（不一致 {total - agree_pred} 条）")
    print(f"人工 vs 原始标注一致率：{result['agreement_human_vs_author_label']:.4f}（人工改标 {len(corrected)} 条）")
    print(f"机器 vs 原始标注一致率（抽检子集）：{result['agreement_machine_vs_author_label']:.4f}")
    if corrected:
        print("\n人工改标的样本：")
        for item in corrected:
            print(f"  {item['id']} [{item['category']}] 原 {item['author_label']} → 人工 {item['human_label']}：{item['human_note']}")

    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n结果已写入 {out_json}")

    if total < math.ceil(0.2 * len(trusted)):
        print(f"\nWARN: 抽检比例 {total / len(trusted):.1%} 低于 20%，不满足交付要求。")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="人工抽检工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sheet = sub.add_parser("sheet", help="生成复核表")
    p_sheet.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p_sheet.add_argument("--predictions", type=Path, default=DEFAULT_PREDS)
    p_sheet.add_argument("--out", type=Path, default=DEFAULT_SHEET)
    p_sheet.add_argument("--mode", default="rules+semantic")
    p_sheet.add_argument("--frac", type=float, default=0.25)
    p_sheet.add_argument("--seed", type=int, default=20260927)

    p_score = sub.add_parser("score", help="统计一致率")
    p_score.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p_score.add_argument("--predictions", type=Path, default=DEFAULT_PREDS)
    p_score.add_argument("--mode", default="rules+semantic")
    p_score.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    p_score.add_argument("--out", type=Path, default=REPO_ROOT / "eval" / "results" / "spotcheck.json")

    args = parser.parse_args(argv)
    if args.cmd == "sheet":
        return make_sheet(args.dataset, args.predictions, args.out, args.mode, args.frac, args.seed)
    return score_sheet(args.sheet, args.out, args.dataset, args.predictions, args.mode)


if __name__ == "__main__":
    sys.exit(main())
