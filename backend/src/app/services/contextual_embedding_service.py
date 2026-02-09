"""上下文增强生成服务。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.settings import Settings, get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.prompts import get_prompt_loader

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ContextResult:
    context: str
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


class ContextualEmbeddingService:
    _SOURCE_MAX_CHARS = 2000

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._prompts = get_prompt_loader()

    async def generate(
        self,
        *,
        full_text: str,
        chunk: str,
        enabled: bool | None = None,
        max_tokens: int | None = None,
    ) -> ContextResult:
        enabled_flag = (
            self._settings.ingestion_contextual_enabled
            if enabled is None
            else enabled
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
        prompt = self._prompts.render(
            "ingestion/contextual_embedding",
            content=source,
            chunk=chunk,
            max_tokens=max_tokens_value,
        )

        start_time = time.perf_counter()
        try:
            result_text = await self._call_llm(prompt, max_tokens=max_tokens_value)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning("Context 生成失败", extra={"error": str(exc)})
            return ContextResult(
                context="",
                success=False,
                reason="error",
                latency_ms=latency_ms,
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        context = (result_text or "").strip()
        if not context:
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

    async def _call_llm(self, prompt: str, *, max_tokens: int) -> str:
        from langchain.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
            profile=build_chat_model_profile(self._settings),
        )
        model = model.bind(max_tokens=max_tokens)

        def _run() -> object:
            return model.invoke([HumanMessage(content=prompt)])

        result = await asyncio.to_thread(_run)
        return getattr(result, "content", "") or ""
