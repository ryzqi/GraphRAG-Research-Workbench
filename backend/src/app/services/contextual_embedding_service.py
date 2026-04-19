"""上下文增强生成服务。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.settings import Settings, get_settings
from app.integrations.chat_model_cache import (
    create_chat_model_cached as create_chat_model,
)
from app.integrations.chat_model_factory import get_active_model_identity
from app.prompts import get_prompt_loader

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ContextResult:
    context: str
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class _LLMCallOutput:
    text: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ContextualEmbeddingService:
    _SOURCE_MAX_CHARS = 2000
    _MIN_MAX_TOKENS = 1

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._prompts = get_prompt_loader()

    @staticmethod
    def _error_reason(exc: Exception) -> str:
        exc_type = type(exc).__name__ or "error"
        message = str(exc).strip()
        if not message:
            return exc_type
        compact = " ".join(message.split())
        if len(compact) > 200:
            compact = compact[:197] + "..."
        return f"{exc_type}: {compact}"

    async def generate(
        self,
        *,
        full_text: str,
        chunk: str,
        enabled: bool | None = None,
        max_tokens: int | None = None,
    ) -> ContextResult:
        enabled_flag = (
            self._settings.ingestion_contextual_enabled if enabled is None else enabled
        )
        if not enabled_flag:
            return ContextResult(context="", success=False, reason="disabled")
        if not chunk.strip():
            return ContextResult(context="", success=False, reason="empty_chunk")

        source = self._extract_source(full_text, chunk)
        max_tokens_value = (
            self._settings.ingestion_contextual_max_tokens
            if max_tokens is None
            else max_tokens
        )
        max_tokens_value = max(int(max_tokens_value), self._MIN_MAX_TOKENS)
        prompt = self._prompts.render_with_few_shot(
            "ingestion/contextual_embedding",
            content=source,
            chunk=chunk,
            max_tokens=max_tokens_value,
        )

        start_time = time.perf_counter()
        try:
            llm_output = await self._call_llm(prompt)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            reason = self._error_reason(exc)
            logger.warning("Context 生成失败", extra={"error": reason})
            return ContextResult(
                context="",
                success=False,
                reason=reason,
                latency_ms=latency_ms,
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        context = (llm_output.text or "").strip()
        if not context:
            model_identity = self._resolve_model_identity()
            logger.warning(
                "Context 生成为空",
                extra={
                    "model": model_identity,
                    "finish_reason": llm_output.finish_reason,
                    "prompt_tokens": llm_output.prompt_tokens,
                    "completion_tokens": llm_output.completion_tokens,
                    "latency_ms": latency_ms,
                },
            )
            return ContextResult(
                context="",
                success=False,
                reason="empty_output",
                latency_ms=latency_ms,
            )

        return ContextResult(
            context=context,
            success=True,
            reason=None,
            latency_ms=latency_ms,
        )

    def _resolve_model_identity(self) -> str | None:
        try:
            provider, model = get_active_model_identity(settings=self._settings)
        except Exception:
            return None
        return f"{provider}/{model}"

    def _extract_source(self, full_text: str, chunk: str) -> str:
        if not full_text:
            return chunk
        idx = full_text.find(chunk)
        if idx < 0:
            return full_text[: self._SOURCE_MAX_CHARS]
        half = self._SOURCE_MAX_CHARS // 2
        start = max(0, idx - half)
        end = min(len(full_text), idx + len(chunk) + half)
        return full_text[start:end]

    async def _call_llm(self, prompt: str) -> _LLMCallOutput:
        from langchain.messages import HumanMessage

        from app.services.streaming import extract_answer_text

        model = create_chat_model(settings=self._settings)

        def _run() -> object:
            return model.invoke([HumanMessage(content=prompt)])

        result = await asyncio.to_thread(_run)
        raw_content = getattr(result, "content", "")
        response_metadata = getattr(result, "response_metadata", {})
        if not isinstance(response_metadata, dict):
            response_metadata = {}

        token_usage = response_metadata.get("token_usage")
        if not isinstance(token_usage, dict):
            token_usage = {}

        return _LLMCallOutput(
            text=extract_answer_text(raw_content),
            finish_reason=response_metadata.get("finish_reason"),
            prompt_tokens=token_usage.get("prompt_tokens"),
            completion_tokens=token_usage.get("completion_tokens"),
        )
