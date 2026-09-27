"""人工抽检：生成复核表并统计一致率（``make spotcheck``）。

为什么要有这一步：数据集是单人构造的，只用"作者标注 vs 检测器"算指标等于自己判自己。
人工抽检把一部分样本**重新过一遍人的眼睛**，报出"机器判定与人工判定的一致率"，
是这份评测里唯一能部分对冲"自证"质疑的证据。它不能完全消除偏差（复核者与构造者是同一人），
报告里必须如实写明这一点。

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
                out[rec["id"]] = rec
    return out


def make_sheet(dataset: Path, preds_path: Path, out: Path, mode: str, frac: float, seed: int) -> int:
    rows = [json.loads(line) for line in dataset.open(encoding="utf-8") if line.strip()]
    preds = _load_predictions(preds_path, mode)

    rng = random.Random(seed)
    # 分层抽样：恶意/正常各按比例抽，保证抽检子集的构成与全集一致
    picked: list[dict] = []
    for label in (1, 0):
        group = [r for r in rows if r["label"] == label]
        k = max(1, round(len(group) * frac))
        picked.extend(rng.sample(group, k))
    picked.sort(key=lambda r: r["id"])

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "id",
                "category",
                "author_label",
                "machine_pred",
                "machine_hits",
                "text",
                "human_label",
                "human_note",
            ]
        )
        for r in picked:
            p = preds.get(r["id"], {})
            writer.writerow(
                [
                    r["id"],
                    r["category"],
                    r["label"],
                    p.get("pred", ""),
                    "|".join(p.get("hits", []) or []),
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


def score_sheet(sheet: Path, out_json: Path | None) -> int:
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    filled = [r for r in rows if str(r.get("human_label", "")).strip() != ""]
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
        "n_dataset": len(rows),
        "spotcheck_frac": round(total / len(rows), 4) if rows else None,
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
    print(f"抽检条数：{total} / {len(rows)}（{result['spotcheck_frac']:.1%}）")
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

    if total < 0.2 * len(rows):
        print(f"\nWARN: 抽检比例 {total / len(rows):.1%} 低于 20%，不满足交付要求。")
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
    p_score.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    p_score.add_argument("--out", type=Path, default=REPO_ROOT / "eval" / "results" / "spotcheck.json")

    args = parser.parse_args(argv)
    if args.cmd == "sheet":
        return make_sheet(args.dataset, args.predictions, args.out, args.mode, args.frac, args.seed)
    return score_sheet(args.sheet, args.out)


if __name__ == "__main__":
    sys.exit(main())
