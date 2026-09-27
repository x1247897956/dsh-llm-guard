"""检测器公共数据模型与文本预处理。"""

import re
from dataclasses import dataclass, field
from typing import Any

#: 零宽字符：常见于"绕过关键词匹配"的注入样本（把 `忽略` 写成 `忽\u200b略`）。
#: 在进入规则匹配前统一剥离——这是规则层最廉价、收益最高的一步归一化。
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")


def normalize(text: str) -> str:
    """把文本归一化到规则可匹配的形式。

    目前只做两件事（刻意保持保守，避免过度归一化引入新的误报）：
    1. 剥离零宽字符；
    2. 统一小写（英文模式大小写不敏感）。

    ⚠️ 归一化后的文本**只用于匹配**；返回给调用方的 ``input`` 永远是原文。
    """
    return _ZERO_WIDTH.sub("", text).lower()


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
