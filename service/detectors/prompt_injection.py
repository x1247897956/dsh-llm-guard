"""提示词注入检测器（规则基线版）。

检测试图覆盖或劫持系统指令的输入，例如：
- 要求模型"忽略以上指令 / 忽略之前的规则"
- 伪造系统角色或新指令
- 试图泄露系统提示词

设计点（见 docs/design-notes.md）：

1. **匹配前归一化**：剥离零宽字符（``忽\\u200b略``）并统一小写，
   否则 ``<<SYS>>`` 这类大写标记会被漏掉。
2. **``system:`` 要求行首/空白前缀**：否则正常的"我们产品的 system prompt 有 200 字"
   会被误判成伪造系统指令——这是这条规则最典型的误报。
"""

import re

from .base import Detection, normalize


class PromptInjectionDetector:
    RISK_TYPE = "prompt_injection"

    # 明确的指令劫持模式
    PATTERNS = [
        re.compile(r"忽略(以上|之前|先前|上述|所有)?(的)?(指令|规则|提示|约束|设定)"),
        re.compile(r"(无视|忘掉|忘记|不要遵守|别遵守)(以上|之前|先前|上述)?[^。\n]{0,8}(的)?(指令|规则|提示|约束|设定)"),
        re.compile(r"你现在(扮演|是|作为)(一个)?(新的|不同的)?角色"),
        re.compile(r"(泄露|打印|输出|告诉我|展示)(你|系统)(的)?(提示词|系统提示|prompt|指令)"),
        re.compile(r"(忽略|无视)[^。\n]{0,20}(system|system prompt)"),
        re.compile(r"you are now"),
        re.compile(r"ignore (all|any|the)? ?(previous|above|prior) (instructions?|rules?|prompts?)"),
        re.compile(r"reveal (your )?(system prompt|instructions?)"),
        re.compile(r"disregard (all|any|the)? ?(previous|above|prior)? ?(instructions?|rules?)"),
    ]

    # 直接伪造系统指令的标记（全部为小写，因为匹配前已 normalize）
    MARKERS = [
        "system:",
        "<|im_start|>system",
        "<<sys>>",
        "[system]",
        "ignore all previous instructions",
        "ignore the above instructions",
        "disregard all previous instructions",
    ]

    def _has_forged_system_marker(self, haystack: str) -> bool:
        """``system:`` 必须位于行首或紧跟空白/引用符，避免命中 "ecosystem:" 之类。"""
        for m in re.finditer(r"system:", haystack):
            start = m.start()
            if start == 0 or haystack[start - 1] in " \t\n\r>*-#":
                return True
        return False

    def detect(self, text: str) -> Detection:
        matches: list[str] = []
        haystack = normalize(text)

        for marker in self.MARKERS:
            if marker == "system:":
                if self._has_forged_system_marker(haystack):
                    matches.append("system:")
                continue
            if marker in haystack:
                matches.append(marker)

        for pattern in self.PATTERNS:
            m = pattern.search(haystack)
            if m:
                matches.append(m.group(0).strip())

        seen: set[str] = set()
        matches = [m for m in matches if not (m in seen or seen.add(m))]

        is_risky = len(matches) > 0
        reason = "检测到提示词注入特征" if is_risky else "未检测到提示词注入特征"
        return Detection(
            risk_type=self.RISK_TYPE,
            is_risky=is_risky,
            reason=reason,
            matches=matches,
        )
