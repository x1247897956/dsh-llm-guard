"""越狱绕过检测器（规则基线版）。

检测试图绕过安全策略的输入，例如：
- DAN（Do Anything Now）类角色劫持
- 要求模型进入"无限制 / 不受约束"模式
- 通过编码、间接表达等方式规避拒绝
"""

import re

from .base import Detection


class JailbreakDetector:
    RISK_TYPE = "jailbreak"

    PATTERNS = [
        re.compile(r"\bDAN\b", re.I),
        re.compile(r"do anything now", re.I),
        re.compile(r"(进入|切换到)(无限制|不受约束|越狱|无审查|开发者)模式", re.I),
        re.compile(r"(无限制|不受约束|没有限制|不设限制)(地)?(回答|响应|执行)", re.I),
        re.compile(r"(绕过|解除|关闭)(你的)?(安全|内容|审查|限制|过滤)", re.I),
        re.compile(r"(你|模型)(不被|不受)(任何)?(规则|限制|约束)", re.I),
        re.compile(r"jailbreak", re.I),
        re.compile(r"(moral|l(imit|ock)|restriction)s? (off|removed|disabled)", re.I),
    ]

    MARKERS = [
        "do anything now",
        "developer mode",
        "开发者模式",
        "越狱模式",
        "unrestricted mode",
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
        reason = "检测到越狱绕过特征" if is_risky else "未检测到越狱绕过特征"
        return Detection(
            risk_type=self.RISK_TYPE,
            is_risky=is_risky,
            reason=reason,
            matches=matches,
        )
