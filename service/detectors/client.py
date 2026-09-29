"""语义层与模型 API 的通信客户端。

设计取舍（详见 docs/design-notes.md）：
- **只依赖 httpx**，直连 OpenAI 兼容的 ``POST /chat/completions``。v1 用 LangChain 的
  ``ChatOpenAI``，为了一个 JSON 分类请求引入整条链式框架，依赖面大且超时/重试不可控。
- **超时 + 有限重试 + 失败降级**：任何网络/解析异常都不会让 ``/scan`` 挂掉，
  而是降级为「该条只由规则层判定」，并把失败计入统计（``/health`` 可见）。
- **不打印 key**：key 只从环境变量读取，日志里只出现 base_url / model / 状态码。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("llm_guard.semantic")

# 加载 service/.env（若存在），使 DEEPSEEK_API_KEY 进入环境变量
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class CallStats:
    """语义层调用统计——用于在评测报告里如实说明失败率。"""

    requested_model: str | None = None
    reported_model: str | None = None
    calls: int = 0
    ok: int = 0
    failed: int = 0
    parse_failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    last_error: str | None = None

    def to_dict(self) -> dict:
        lat = sorted(self.latencies_ms)
        return {
            "requested_model": self.requested_model,
            "reported_model": self.reported_model,
            "calls": self.calls,
            "ok": self.ok,
            "failed": self.failed,
            "parse_failed": self.parse_failed,
            "failure_rate": round(self.failed / self.calls, 4) if self.calls else 0.0,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms_p50": lat[len(lat) // 2] if lat else None,
            "latency_ms_p95": lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else None,
            "last_error": self.last_error,
        }


def empty_stats_dict() -> dict:
    """未启用语义层时的统计占位（保证 ``/health`` 字段形状恒定）。

    真实教训：这一条是被 CI 抓出来的——没配 key 时 ``semantic_client`` 是 ``None``，
    于是 ``/health`` 取 ``.stats`` 直接 500。降级路径自己崩掉，比不降级更糟。
    """
    return CallStats().to_dict()


class LLMClient:
    """极小的 OpenAI 兼容 chat/completions 客户端。"""

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("LLM_GUARD_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("LLM_GUARD_MODEL") or DEFAULT_MODEL
        self.timeout = float(timeout or os.environ.get("LLM_GUARD_TIMEOUT") or 30)
        self.retries = int(retries if retries is not None else os.environ.get("LLM_GUARD_RETRIES") or 2)
        self.stats = CallStats(requested_model=self.model)
        #: 服务端实际返回的 model 字段（可能与请求的 model 不同，报告里如实记录）
        self.reported_model: str | None = None

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 200) -> str:
        """调用模型并返回文本内容。失败时抛 ``RuntimeError``（由调用方降级）。"""
        import httpx

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = "request failed"
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            self.stats.calls += 1
            retryable = True
            last_error = "request failed"
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                if resp.status_code >= 400:
                    retryable = resp.status_code == 429 or resp.status_code >= 500
                    # Upstream bodies can echo credentials or scanned input.
                    last_error = f"HTTP {resp.status_code}"
                    raise RuntimeError(last_error)

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("invalid content")
                reported_model = data.get("model")
                if isinstance(reported_model, str) and reported_model:
                    self.reported_model = reported_model
                    self.stats.reported_model = reported_model
                usage = data.get("usage")
                if isinstance(usage, dict):
                    for name in ("prompt_tokens", "completion_tokens"):
                        value = usage.get(name, 0)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            setattr(self.stats, name, getattr(self.stats, name) + value)
                self.stats.ok += 1
                return content
            except Exception as exc:  # noqa: BLE001 - network/parser failures degrade
                self.stats.failed += 1
                # Never retain arbitrary exception text (URLs, bodies, keys, input).
                if isinstance(exc, httpx.TimeoutException):
                    last_error = "timeout"
                elif isinstance(exc, httpx.RequestError):
                    last_error = "network error"
                elif not last_error.startswith("HTTP "):
                    last_error = "invalid response"
                self.stats.last_error = last_error
            finally:
                self.stats.latencies_ms.append((time.monotonic() - started) * 1000)
            if not retryable:
                break
            if attempt < self.retries:
                time.sleep(0.5 * (2**attempt))
            last_error = self.stats.last_error or "request failed"

        raise RuntimeError(f"语义层调用失败：{last_error}") from None
