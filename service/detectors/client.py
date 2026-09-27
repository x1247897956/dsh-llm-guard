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
        self.stats = CallStats()
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

        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            self.stats.calls += 1
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                elapsed_ms = (time.monotonic() - started) * 1000
                self.stats.latencies_ms.append(elapsed_ms)

                if resp.status_code >= 500 or resp.status_code == 429:
                    # 可重试的服务端/限流错误
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                if resp.status_code >= 400:
                    # 4xx（鉴权/参数）重试无意义，直接失败
                    raise PermissionError(f"HTTP {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                self.reported_model = data.get("model") or self.reported_model
                usage = data.get("usage") or {}
                self.stats.prompt_tokens += usage.get("prompt_tokens", 0)
                self.stats.completion_tokens += usage.get("completion_tokens", 0)
                self.stats.ok += 1
                return data["choices"][0]["message"]["content"]
            except PermissionError:
                self.stats.failed += 1
                self.stats.last_error = "auth/param error"
                raise
            except Exception as exc:  # noqa: BLE001 - 网络层异常统一重试
                last_err = exc
                self.stats.last_error = f"{type(exc).__name__}"
                if attempt < self.retries:
                    time.sleep(0.5 * (2**attempt))  # 指数退避：0.5s, 1s, ...

        self.stats.failed += 1
        raise RuntimeError(f"语义层调用失败（已重试 {self.retries} 次）：{last_err}")
