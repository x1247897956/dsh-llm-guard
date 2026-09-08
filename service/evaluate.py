"""评测脚本：跑 Scanner，输出检出率/误报率等指标。

用法：
    cd service
    uv run --with fastapi --with pydantic --with langchain-openai --with python-dotenv python evaluate.py
"""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service.eval_dataset import DATASET, MALICIOUS, BENIGN
from service.scanner import Scanner


def main() -> None:
    scanner = Scanner()

    tp = 0  # 恶意样本被正确检出
    fn = 0  # 恶意样本被漏掉
    fp = 0  # 正常样本被误报
    tn = 0  # 正常样本被正确放行

    # 按风险类型统计检出
    per_type = Counter()
    per_type_total = Counter()

    for text, label, risk in DATASET:
        result = scanner.scan(text)
        detected_risky = result.risky

        if label:  # 恶意
            per_type_total[risk] += 1
            if detected_risky:
                tp += 1
                per_type[risk] += 1
            else:
                fn += 1
        else:  # 正常
            if detected_risky:
                fp += 1
            else:
                tn += 1

    total_malicious = tp + fn
    total_benign = fp + tn

    recall = tp / total_malicious if total_malicious else 0.0        # 检出率/召回率
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    fpr = fp / total_benign if total_benign else 0.0                  # 误报率
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print("=" * 50)
    print("LLM Guard 评测结果")
    print("=" * 50)
    print(f"恶意样本: {total_malicious}  正常样本: {total_benign}")
    print(f"检出 (TP): {tp}  漏报 (FN): {fn}  误报 (FP): {fp}  正确放行 (TN): {tn}")
    print("-" * 50)
    print(f"检出率 (Recall):    {recall:.1%}")
    print(f"精确率 (Precision): {precision:.1%}")
    print(f"误报率 (FPR):       {fpr:.1%}")
    print(f"F1:                 {f1:.3f}")
    print("-" * 50)
    print("分类型检出率:")
    for risk, total in sorted(per_type_total.items()):
        print(f"  {risk:<20} {per_type[risk]}/{total}")
    print("=" * 50)


if __name__ == "__main__":
    main()
