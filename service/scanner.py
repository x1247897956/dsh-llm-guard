"""扫描引擎：汇总所有规则检测器，产出统一风险报告。

LLM 语义检测层为可选挂载点：当配置了模型 API 时，
可在此追加一个 semantic 检测器做规则覆盖不到的变形攻击识别。
"""

from .detectors import (
    JailbreakDetector,
    PromptInjectionDetector,
    SensitiveDataDetector,
    SemanticDetector,
)
from .detectors.base import ScanResult


class Scanner:
    def __init__(self) -> None:
        self.rule_detectors = [
            PromptInjectionDetector(),
            JailbreakDetector(),
            SensitiveDataDetector(),
        ]
        self.semantic_detector = SemanticDetector()

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(input=text, risky=False)

        for detector in self.rule_detectors:
            detection = detector.detect(text)
            if detection.is_risky:
                result.risky = True
            result.detections.append(detection)

        # 语义检测：仅识别注入/越狱两类（规则可能漏的变形攻击）
        semantic = self.semantic_detector.detect(text)
        if semantic is not None:
            if semantic.is_risky:
                result.risky = True
            result.detections.append(semantic)

        return result
