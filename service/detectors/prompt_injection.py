"""提示词注入检测器（规则基线版）。

检测试图覆盖或劫持系统指令的输入，例如：
- 要求模型"忽略以上指令 / 忽略之前的规则"
- 伪造系统角色或新指令
- 试图泄露系统提示词
"""

import re

from .base import Detection


class PromptInjectionDetector:
    RISK_TYPE = "prompt_injection"

    # 明确的指令劫持模式
    PATTERNS = [
        re.compile(r"忽略(以上|之前|先前|上述|所有)?(的)?(指令|规则|提示|约束)", re.I),
        re.compile(r"(无视|忘掉|忘记|不要遵守|别遵守)(以上|之前|先前|上述)?(的)?(指令|规则|提示|约束)", re.I),
        re.compile(r"你现在(扮演|是|作为)(一个)?(新的|不同的)?角色", re.I),
        re.compile(r"(泄露|打印|输出|告诉我)(你|系统)(的)?(提示词|系统提示|prompt|指令)", re.I),
        re.compile(r"(忽略|无视).*(system|system prompt)", re.I),
        re.compile(r"you are now", re.I),
        re.compile(r"ignore (all|previous|above) (instructions?|rules?|prompts?)", re.I),
        re.compile(r"reveal (your )?(system prompt|instructions?)", re.I),
    ]

    # 直接伪造系统指令的标记
    MARKERS = [
        "system:",
        "<|im_start|>system",
        "<<SYS>>",
        "ignore all previous instructions",
        "ignore the above instructions",
        "disregard all previous instructions",
    ]

    def detect(self, text: str) -> Detection:
        matches: list[str] = []

        lowered = text.lower()
        for marker in self.MARKERS:
            if marker in lowered:
                matches.append(marker)

        for pattern in self.PATTERNS:
            m = pattern.search(text)
            if m:
                matches.append(m.group(0))

        is_risky = len(matches) > 0
        reason = (
            "检测到提示词注入特征" if is_risky else "未检测到提示词注入特征"
        )
        return Detection(
            risk_type=self.RISK_TYPE,
            is_risky=is_risky,
            reason=reason,
            matches=matches,
        )
