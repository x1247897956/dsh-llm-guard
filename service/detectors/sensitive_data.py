"""敏感数据外泄检测器（规则基线版）。

检测文本中泄露的敏感信息：
- 各类 API 密钥 / Token
- 云服务凭据
- 手机号、身份证号、邮箱等个人信息
"""

import re

from .base import Detection


class SensitiveDataDetector:
    RISK_TYPE = "sensitive_data"

    PATTERNS: list[tuple[str, re.Pattern]] = [
        ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")),
        ("aws_secret_key", re.compile(r"\b(?=.*[A-Z])(?=.*[a-z])(?=.*\d)[A-Za-z0-9/+=]{40}\b")),
        ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
        ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
        ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
        ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
        ("private_key", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
        ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
        ("cn_phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
        ("cn_id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
        ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ]

    def detect(self, text: str) -> Detection:
        matches: list[str] = []

        for name, pattern in self.PATTERNS:
            m = pattern.search(text)
            if m:
                matches.append(f"{name}: {m.group(0)}")

        is_risky = len(matches) > 0
        reason = "检测到敏感数据外泄" if is_risky else "未检测到敏感数据外泄"
        return Detection(
            risk_type=self.RISK_TYPE,
            is_risky=is_risky,
            reason=reason,
            matches=matches,
        )
