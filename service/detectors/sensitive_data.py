"""敏感数据外泄检测器（规则基线版）。

检测文本中泄露的敏感信息：
- 各类 API 密钥 / Token（AWS / GitHub / OpenAI / Anthropic / Google / PEM / JWT）
- 云服务凭据
- 手机号、身份证号、邮箱等个人信息

两个刻意的设计点：

1. **身份证号做校验位验证**。纯 ``\\d{17}[\\dX]`` 会把 18 位订单号、流水号全判成身份证，
   是这条规则最大的误报来源；加上 GB 11643 校验位后误报显著下降（见 docs/design-notes.md）。
2. 只报**第一条**命中值。护栏场景关心"是否有敏感数据"，不关心把全文的 PII 全列出来
   （那等于把敏感数据又抄了一遍）。
"""

import re

from .base import Detection

# GB 11643-1999 身份证号校验位权重与映射
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECKSUM = "10X98765432"
_ID_CANDIDATE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")


def is_valid_cn_id(candidate: str) -> bool:
    """校验 18 位身份证号的校验位（不校验地区码与出生日期合法性）。"""
    total = sum(int(ch) * w for ch, w in zip(candidate[:17], _ID_WEIGHTS))
    return candidate[17].upper() == _ID_CHECKSUM[total % 11]


class SensitiveDataDetector:
    RISK_TYPE = "sensitive_data"

    PATTERNS: list[tuple[str, re.Pattern]] = [
        ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")),
        ("aws_secret_key", re.compile(r"\b(?=.*[A-Z])(?=.*[a-z])(?=.*\d)[A-Za-z0-9/+=]{40}\b")),
        ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
        ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
        ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
        ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
        ("private_key", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
        ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
        ("cn_phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
        ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ]

    def detect(self, text: str) -> Detection:
        matches: list[str] = []

        for name, pattern in self.PATTERNS:
            m = pattern.search(text)
            if m:
                matches.append(f"{name}: {m.group(0)}")

        # 身份证号：先匹配形态，再验校验位
        id_match = _ID_CANDIDATE.search(text)
        if id_match and is_valid_cn_id(id_match.group(1)):
            matches.append(f"cn_id_card: {id_match.group(1)}")

        is_risky = len(matches) > 0
        reason = "检测到敏感数据外泄" if is_risky else "未检测到敏感数据外泄"
        return Detection(
            risk_type=self.RISK_TYPE,
            is_risky=is_risky,
            reason=reason,
            matches=matches,
        )
