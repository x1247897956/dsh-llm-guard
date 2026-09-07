"""检测器公共数据模型。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Detection:
    """单条风险判定结果。"""

    risk_type: str          # prompt_injection / jailbreak / sensitive_data
    is_risky: bool
    reason: str
    matches: list[str] = field(default_factory=list)  # 命中的具体规则/关键词


@dataclass
class ScanResult:
    """一次扫描的汇总结果。"""

    input: str
    risky: bool
    detections: list[Detection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "risky": self.risky,
            "detections": [
                {
                    "risk_type": d.risk_type,
                    "is_risky": d.is_risky,
                    "reason": d.reason,
                    "matches": d.matches,
                }
                for d in self.detections
            ],
        }
