"""扫描引擎：汇总所有规则检测器，产出统一风险报告。

LLM 语义检测层为可选挂载点：当配置了模型 API 时，
可在此追加一个 semantic 检测器做规则覆盖不到的变形攻击识别。
"""

from .detectors import (
    JailbreakDetector,
    PromptInjectionDetector,
    SensitiveDataDetector,
)
from .detectors.base import ScanResult


class Scanner:
    def __init__(self) -> None:
        self.detectors = [
            PromptInjectionDetector(),
            JailbreakDetector(),
            SensitiveDataDetector(),
        ]

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(input=text, risky=False)

        for detector in self.detectors:
            detection = detector.detect(text)
            if detection.is_risky:
                result.risky = True
            result.detections.append(detection)

        return result
