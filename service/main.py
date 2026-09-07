"""LLM Guard 检测服务（FastAPI）。

提供 POST /scan 接口，接收文本，返回统一风险报告。
DSH 工具插件通过此接口桥接 Python/LangChain 检测核心。
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .scanner import Scanner

app = FastAPI(title="LLM Guard", version="0.1.0")
scanner = Scanner()


class ScanRequest(BaseModel):
    text: str = Field(..., description="待检测的 prompt / 对话文本")


class ScanResponse(BaseModel):
    input: str
    risky: bool
    detections: list[dict]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    result = scanner.scan(req.text)
    return ScanResponse(**result.to_dict())
