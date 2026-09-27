"""越狱绕过检测器（规则基线版）。

检测试图绕过安全策略的输入，例如：
- DAN（Do Anything Now）类角色劫持
- 要求模型进入"无限制 / 不受约束"模式
- 通过编码、间接表达等方式规避拒绝

两个刻意的设计点（见 docs/design-notes.md）：

1. **``DAN`` 不裸匹配**。``\\bDAN\\b`` 会把"这个人的英文名缩写是 Dan"这类正常文本判成越狱，
   是纯正则最典型的误报；这里要求 ``DAN`` 与"模式 / 越狱 / 角色扮演 / do anything now"
   共现，或出现在明示越狱的语境中。
2. **零宽字符归一化**：``忽\\u200b略`` / ``jail\\u200bbreak`` 是常见绕过手法，
   匹配前统一剥离（在 ``base.normalize`` 里做）。
"""

import re

from .base import Detection, normalize


class JailbreakDetector:
    RISK_TYPE = "jailbreak"

    PATTERNS = [
        # DAN 必须与越狱语境共现（避免命中英文名 / 代号 / 数据集名）
        re.compile(r"dan\s*(模式|越狱)"),
        re.compile(r"(进入|启用|切换(到)?|开启)\s*dan\b"),
        re.compile(r"\bdan\b[^。\n]{0,12}(do anything now|模式|角色|越狱)"),
        re.compile(r"do anything now"),
        re.compile(r"(进入|切换到)(无限制|不受约束|越狱|无审查|开发者)模式"),
        re.compile(r"(无限制|不受约束|没有限制|不设限制)(地)?(回答|响应|执行)"),
        re.compile(r"(绕过|解除|关闭|去掉|取消)(你的)?(安全|内容|审查|限制|过滤|防护)"),
        re.compile(r"(你的|模型的)?(限制|安全策略|约束|防护)(已经)?(关闭|解除|失效|被移除|去掉了)"),
        re.compile(r"(你|模型)(不被|不受)(任何)?(规则|限制|约束)"),
        re.compile(r"jailbreak"),
        re.compile(r"(restrictions?|limits?|morals?)\s+(are\s+)?(off|removed|disabled|gone)"),
        re.compile(r"(unrestricted|unfiltered|uncensored)\s+mode"),
    ]

    MARKERS = [
        "do anything now",
        "developer mode",
        "开发者模式",
        "越狱模式",
        "unrestricted mode",
        "unfiltered mode",
    ]

    def detect(self, text: str) -> Detection:
        matches: list[str] = []
        haystack = normalize(text)

        for marker in self.MARKERS:
            if marker in haystack:
                matches.append(marker)

        for pattern in self.PATTERNS:
            m = pattern.search(haystack)
            if m:
                matches.append(m.group(0).strip())

        # 去重但保持顺序
        seen: set[str] = set()
        matches = [m for m in matches if not (m in seen or seen.add(m))]

        is_risky = len(matches) > 0
        reason = "检测到越狱绕过特征" if is_risky else "未检测到越狱绕过特征"
        return Detection(
            risk_type=self.RISK_TYPE,
            is_risky=is_risky,
            reason=reason,
            matches=matches,
        )
