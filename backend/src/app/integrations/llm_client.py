"""LLM 客户端。

统一走模型配置页维护的全局模型配置（openai/ollama/nvidia）。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from app.core.model_config_errors import ModelConfigIncompleteError
from app.core.settings import get_settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.integrations.chat_model_factory import get_active_model_identity
from app.services.streaming import extract_answer_text

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChatMessage:
    """聊天消息。"""

    role: str
    content: str
    response_id: str | None = None


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
        http_client: object | None = None,
    ) -> None:
        settings = get_settings()
        self._settings = settings
        self._http_client = http_client

    async def chat_with_metrics(
        self,
        *,
        messages: list[ChatMessage],
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """带指标的聊天接口。"""
        timeout = (
            self._settings.llm_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )

        start_time = time.perf_counter()
        last_exc: Exception | None = None

        lc_messages = [self._to_langchain_message(message) for message in messages]

        async def _run() -> LLMResponse:
            nonlocal last_exc
            for attempt in range(2):
                try:
                    chat_model, provider_name, model_name = self._build_chat_model(
                        timeout=timeout
                    )
                    data = await self._invoke_chat_model(
                        chat_model=chat_model,
                        messages=lc_messages,
                        timeout=timeout,
                    )

                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    usage = self._extract_usage(data)

                    logger.info(
                        "LLM 调用完成",
                        extra={
                            "provider": provider_name,
                            "model": model_name,
                            "prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0),
                            "latency_ms": latency_ms,
                            "attempt": attempt + 1,
                        },
                    )

                    return LLMResponse(
                        content=self._extract_content(data),
                        model=model_name,
                        usage=usage,
                        latency_ms=latency_ms,
                    )
                except Exception as exc:  # pragma: no cover
                    if isinstance(exc, ModelConfigIncompleteError):
                        raise
                    last_exc = exc
                    logger.warning(f"LLM 调用失败 (attempt {attempt + 1}): {exc}")
                    if attempt < 1:
                        delay = 0.2 * (2**attempt)
                        delay = delay * (1 + random.random() * 0.2)
                        await asyncio.sleep(delay)
            raise RuntimeError("LLM 调用失败") from last_exc

        return await _run()

    def _build_chat_model(self, *, timeout: float) -> tuple[Any, str, str]:
        del timeout
        provider_name, model_name = get_active_model_identity(settings=self._settings)
        return create_chat_model(settings=self._settings), provider_name, model_name

    async def _invoke_chat_model(
        self,
        *,
        chat_model: Any,
        messages: list[SystemMessage | HumanMessage | AIMessage],
        timeout: float,
    ) -> object:
        async def _call() -> object:
            ainvoke = getattr(chat_model, "ainvoke", None)
            if callable(ainvoke):
                result = ainvoke(messages)
                if inspect.isawaitable(result):
                    return await result
                return result

            invoke = getattr(chat_model, "invoke", None)
            if not callable(invoke):
                raise RuntimeError("ChatModel does not support invoke/ainvoke")
            return await asyncio.to_thread(invoke, messages)

        if timeout > 0:
            return await asyncio.wait_for(_call(), timeout=timeout)
        return await _call()

    @staticmethod
    def _to_langchain_message(
        message: ChatMessage,
    ) -> SystemMessage | HumanMessage | AIMessage:
        role = message.role.strip().lower()
        if role == "assistant":
            return AIMessage(content=message.content)
        if role == "system":
            return SystemMessage(content=message.content)
        return HumanMessage(content=message.content)

    @staticmethod
    def _extract_content(raw: object) -> str:
        content = getattr(raw, "content", "")
        return extract_answer_text(content)

    @staticmethod
    def _extract_usage(raw: object) -> dict[str, int]:
        usage: dict[str, int] = {}

        response_metadata = getattr(raw, "response_metadata", None)
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                usage.update(
                    LLMClient._coerce_token_usage(
                        prompt_tokens=token_usage.get("prompt_tokens"),
                        completion_tokens=token_usage.get("completion_tokens"),
                        total_tokens=token_usage.get("total_tokens"),
                    )
                )
            fallback_usage = response_metadata.get("usage")
            if isinstance(fallback_usage, dict):
                usage.update(
                    LLMClient._coerce_token_usage(
                        prompt_tokens=fallback_usage.get("prompt_tokens")
                        or fallback_usage.get("input_tokens"),
                        completion_tokens=fallback_usage.get("completion_tokens")
                        or fallback_usage.get("output_tokens"),
                        total_tokens=fallback_usage.get("total_tokens"),
                    )
                )

        usage_metadata = getattr(raw, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            usage.update(
                LLMClient._coerce_token_usage(
                    prompt_tokens=usage_metadata.get("input_tokens")
                    or usage_metadata.get("prompt_tokens"),
                    completion_tokens=usage_metadata.get("output_tokens")
                    or usage_metadata.get("completion_tokens"),
                    total_tokens=usage_metadata.get("total_tokens"),
                )
            )

        return usage

    @staticmethod
    def _coerce_token_usage(
        *,
        prompt_tokens: object,
        completion_tokens: object,
        total_tokens: object,
    ) -> dict[str, int]:
        data: dict[str, int] = {}
        if isinstance(prompt_tokens, int):
            data["prompt_tokens"] = prompt_tokens
        if isinstance(completion_tokens, int):
            data["completion_tokens"] = completion_tokens
        if isinstance(total_tokens, int):
            data["total_tokens"] = total_tokens
        if "total_tokens" not in data and {
            "prompt_tokens",
            "completion_tokens",
        }.issubset(data):
            data["total_tokens"] = data["prompt_tokens"] + data["completion_tokens"]
        return data
