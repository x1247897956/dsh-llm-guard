"""LLM Guard 检测服务（FastAPI）。

对外契约：
- ``GET  /health``  健康检查 + 当前检测能力（规则层 / 语义层是否启用）
- ``POST /scan``    单条文本检测，返回 ``{input, risky, detections}``

``/scan`` 的字段保持 v1 原样（向后兼容），另外**新增可选**查询参数 ``mode``：

- 省略 / ``rules+semantic``：规则层 + 语义层（默认行为，与 v1 等价）
- ``rules``：只跑规则层（不产生模型调用，确定性、可离线）
- ``semantic``：只跑语义层（用于消融对照）
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .detectors.client import empty_stats_dict
from .scanner import MODES, Scanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("llm_guard")

app = FastAPI(
    title="LLM Guard",
    version="0.2.0",
    description="LLM 应用输入侧安全检测：规则 + 语义双层护栏",
)
scanner = Scanner()

logger.info(
    "LLM Guard 启动：语义层 enabled=%s，规则集 prompt_injection/jailbreak/sensitive_data",
    scanner.semantic_enabled,
)


class ScanRequest(BaseModel):
    text: str = Field(..., description="待检测的 prompt / 对话文本")


class ScanResponse(BaseModel):
    input: str
    risky: bool
    detections: list[dict]


@app.get("/health")
def health() -> dict:
    """健康检查：同时暴露语义层可用性，避免「静默降级」被误读成检测失败。

    未启用语义层时 ``semantic_client`` 为 ``None``，这里退化为一份零值统计，
    保证响应字段形状恒定（调用方不必写两套解析逻辑）。
    """
    client = scanner.semantic_client
    return {
        "status": "ok",
        "version": app.version,
        "detectors": {
            "rules": [d.RISK_TYPE for d in scanner.rule_detectors],
            "semantic_enabled": scanner.semantic_enabled,
            "semantic_model": None if client is None else client.model,
            "semantic_base_url": None if client is None else client.base_url,
        },
        "semantic_stats": client.stats.to_dict() if client is not None else empty_stats_dict(),
    }


@app.post("/scan", response_model=ScanResponse)
def scan(
    req: ScanRequest,
    mode: str = Query(
        default="rules+semantic",
        description=f"检测模式，可选：{', '.join(MODES)}",
    ),
) -> ScanResponse:
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"mode 必须是 {MODES} 之一")
    result = scanner.scan(req.text, mode=mode)
    return ScanResponse(**result.to_dict())
