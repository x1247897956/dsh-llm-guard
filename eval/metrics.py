"""指标计算：混淆矩阵 + 分类别 precision / recall / F1 / FPR。

口径（与 docs/eval-report.md 的公式表一致）：

- 正类 = 恶意（label=1），负类 = 正常（label=0）
- ``precision = TP / (TP + FP)``
- ``recall    = TP / (TP + FN)``
- ``F1        = 2PR / (P + R)``
- ``FPR       = FP / (FP + TN)``   （负样本中被误判为恶意的比例）
- ``accuracy  = (TP + TN) / N``

分母为 0 时返回 ``None`` 而不是 0.0 —— 宁可在报告里显示 ``n/a``，
也不要把"没有样本"伪装成"指标为 0"。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def positives(self) -> int:
        return self.tp + self.fn

    @property
    def negatives(self) -> int:
        return self.fp + self.tn

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return round(self.tp / denom, 4) if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return round(self.tp / denom, 4) if denom else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return round(2 * p * r / (p + r), 4)

    @property
    def fpr(self) -> float | None:
        denom = self.fp + self.tn
        return round(self.fp / denom, 4) if denom else None

    @property
    def fnr(self) -> float | None:
        denom = self.tp + self.fn
        return round(self.fn / denom, 4) if denom else None

    @property
    def accuracy(self) -> float | None:
        return round((self.tp + self.tn) / self.n, 4) if self.n else None

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "positives": self.positives,
            "negatives": self.negatives,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "fpr": self.fpr,
            "fnr": self.fnr,
            "accuracy": self.accuracy,
        }


def confusion(pairs: list[tuple[int, int]]) -> Confusion:
    """``pairs`` 为 ``(label, prediction)`` 列表。"""
    c = Confusion()
    for label, pred in pairs:
        if label == 1 and pred == 1:
            c.tp += 1
        elif label == 0 and pred == 1:
            c.fp += 1
        elif label == 1 and pred == 0:
            c.fn += 1
        else:
            c.tn += 1
    return c
