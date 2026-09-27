"""敏感数据规则检测器测试。

所有凭据均为**明显造假的测试值**，不对应任何真实账号。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest

from service.detectors.sensitive_data import SensitiveDataDetector

# (文本, 期望命中的规则名)
TYPED_CASES = [
    ("key: AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
    ("token: ghp_" + "a" * 36, "github_token"),
    ("key: sk-TESTONLY0000000000000000", "openai_api_key"),
    ("key: sk-ant-TESTONLY0000000000000000", "anthropic_api_key"),
    ("key: AIza" + "T" * 35, "google_api_key"),
    ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private_key"),
    (
        "token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "jwt",
    ),
    ("客户电话 13800138000，麻烦回访", "cn_phone"),
    ("身份证号 110101199003071233", "cn_id_card"),
    ("联系我：tester@example.com", "email"),
]


@pytest.mark.parametrize("text,expected_type", TYPED_CASES)
def test_sensitive_types_detected(text, expected_type):
    result = SensitiveDataDetector().detect(text)
    assert result.is_risky, f"应检出敏感数据：{text}"
    assert result.risk_type == "sensitive_data"
    assert any(m.startswith(f"{expected_type}:") for m in result.matches), result.matches


@pytest.mark.parametrize(
    "text",
    [
        "今天天气不错",
        "帮我把这段中文翻译成英文",
        "订单号 2024092712345678901234 已发货",  # 24 位订单号不应被当作身份证
        "编号 123456789012345678",  # 18 位纯数字，校验位不合法 → 不是身份证
        "流水号 110101199003071234 已登记",  # 形态像但校验位错的号
        "版本号 v1.2.3 已发布",
        "我的邮箱是 a@b 这样写对吗",
    ],
)
def test_sensitive_negative(text):
    result = SensitiveDataDetector().detect(text)
    assert not result.is_risky, f"不应检出敏感数据：{text} → {result.matches}"


def test_id_card_requires_valid_checksum():
    """身份证号必须过 GB 11643 校验位——这是这条规则的主要误报来源。"""
    from service.detectors.sensitive_data import is_valid_cn_id

    assert is_valid_cn_id("110101199003071233")
    assert not is_valid_cn_id("110101199003071234")
    assert not is_valid_cn_id("123456789012345678")


def test_phone_boundary_digits():
    """手机号必须独立成号，不能被更长数字串包含。"""
    d = SensitiveDataDetector()
    assert d.detect("13800138000").is_risky
    assert not d.detect("138001380001").is_risky
    assert not d.detect("013800138000").is_risky


def test_matches_record_rule_name_and_value():
    result = SensitiveDataDetector().detect("邮箱 tester@example.com")
    assert result.matches == ["email: tester@example.com"]
