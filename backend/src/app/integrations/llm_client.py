"""LLM 客户端。

提供与 OpenAI 兼容 API 的交互，支持指标收集。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import httpx

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatMessage:
    """聊天消息。"""

    role: str
    content: str


@dataclass(slots=True)
class LLMResponse:
    """LLM 响应（含指标）。"""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0


class LLMClient:
    """LLM 客户端。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self._http_client = http_client
        self._base_url = (
            base_url if base_url is not None else settings.llm_base_url
        ).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.llm_api_key
        self._model = model if model is not None else settings.llm_model

    async def chat_with_metrics(
        self,
        *,
        messages: list[ChatMessage],
        timeout_seconds: float = 30.0,
    ) -> LLMResponse:
        """带指标的聊天接口。"""
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        start_time = time.perf_counter()
        last_exc: Exception | None = None

        async def _run(client: httpx.AsyncClient) -> LLMResponse:
            nonlocal last_exc
            for attempt in range(2):
                try:
                    resp = await client.post(
                        url, json=payload, headers=headers, timeout=timeout_seconds
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    usage = data.get("usage", {})

                    logger.info(
                        "LLM 调用完成",
                        extra={
                            "model": self._model,
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "latency_ms": latency_ms,
                            "attempt": attempt + 1,
                        },
                    )

                    return LLMResponse(
                        content=data["choices"][0]["message"]["content"],
                        model=self._model,
                        usage=usage,
                        latency_ms=latency_ms,
                    )
                except Exception as exc:  # pragma: no cover
                    last_exc = exc
                    logger.warning(f"LLM 调用失败 (attempt {attempt + 1}): {exc}")
                    if attempt < 1:
                        delay = 0.2 * (2**attempt)
                        delay = delay * (1 + random.random() * 0.2)
                        await asyncio.sleep(delay)
            raise RuntimeError("LLM 调用失败") from last_exc

        if self._http_client is not None:
            return await _run(self._http_client)

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await _run(client)
