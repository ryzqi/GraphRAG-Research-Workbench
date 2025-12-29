"""LLM 客户端。

提供与 OpenAI 兼容 API 的交互，支持指标收集。
"""

from __future__ import annotations

import logging
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

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.llm_base_url.rstrip("/")
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model

    async def chat(
        self, *, messages: list[ChatMessage], timeout_seconds: float = 30.0
    ) -> str:
        """聊天接口（兼容旧版）。"""
        response = await self.chat_with_metrics(
            messages=messages, timeout_seconds=timeout_seconds
        )
        return response.content

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

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            for attempt in range(2):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
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

        raise RuntimeError("LLM 调用失败") from last_exc
