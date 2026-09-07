"""LLM 应用安全检测器集合。

包含三类规则检测器：
- PromptInjectionDetector：提示词注入
- JailbreakDetector：越狱绕过
- SensitiveDataDetector：敏感数据外泄

每个检测器输出统一的风险判定结构，供上层 /scan 接口汇总。
"""

from .prompt_injection import PromptInjectionDetector
from .jailbreak import JailbreakDetector
from .sensitive_data import SensitiveDataDetector

__all__ = [
    "PromptInjectionDetector",
    "JailbreakDetector",
    "SensitiveDataDetector",
]
