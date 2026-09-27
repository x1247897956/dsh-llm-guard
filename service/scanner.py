"""扫描引擎：汇总规则检测器与语义检测器，产出统一风险报告。"""

from __future__ import annotations

from .detectors import (
    JailbreakDetector,
    PromptInjectionDetector,
    SensitiveDataDetector,
    SemanticDetector,
)
from .detectors.base import Detection, ScanResult

#: 支持的检测模式。``rules`` 不产生任何模型调用，用于消融对照与离线回归。
#: 所有 ``semantic`` 模式共用同一份 prompt（``semantic.PROMPT_VERSION``），
#: 因此各配置的指标口径一致、可直接横向对比。
MODES = ("rules+semantic", "rules", "semantic", "semantic+exfil", "rules+semantic+exfil")

#: 需要额外做"凭据外泄意图"判定的模式
EXFIL_MODES = ("semantic+exfil", "rules+semantic+exfil")
#: 需要调用语义层的模式
SEMANTIC_MODES = ("rules+semantic", "semantic", "semantic+exfil", "rules+semantic+exfil")


class Scanner:
    """把规则层与语义层的判定汇总成一份报告。

    判定口径：**任一层命中即 risky**（并集）。这是护栏场景的默认取舍——
    宁可多报一条待人工确认，也不放过一条真的注入（理由见 docs/design-notes.md）。
    """

    def __init__(self) -> None:
        self.rule_detectors = [
            PromptInjectionDetector(),
            JailbreakDetector(),
            SensitiveDataDetector(),
        ]
        self.semantic_detector = SemanticDetector()

    @property
    def semantic_enabled(self) -> bool:
        return self.semantic_detector.enabled

    @property
    def semantic_client(self):
        return self.semantic_detector.client

    def scan(self, text: str, mode: str = "rules+semantic") -> ScanResult:
        if mode not in MODES:
            raise ValueError(f"mode 必须是 {MODES} 之一，收到 {mode!r}")

        detections: list[Detection] = []

        if mode in ("rules+semantic", "rules", "rules+semantic+exfil"):
            for detector in self.rule_detectors:
                detections.append(detector.detect(text))

        if mode in SEMANTIC_MODES:
            # 语义层默认只判注入 / 越狱；exfil 档额外判"凭据外泄意图"
            # （见 docs/design-notes.md：这是可选的扩展档，默认关闭）。
            semantic = self.semantic_detector.detect(text, include_exfil=mode in EXFIL_MODES)
            if semantic is not None:
                detections.append(semantic)

        return ScanResult(
            input=text,
            risky=any(d.is_risky for d in detections),
            detections=detections,
        )
