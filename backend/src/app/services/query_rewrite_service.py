"""查询重写服务。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.settings import Settings, get_settings
from app.prompts import get_prompt_loader

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RewriteResult:
    query: str
    rewritten: bool
    reason: str | None = None
    latency_ms: int | None = None


class QueryRewriteService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._prompts = get_prompt_loader()

    async def rewrite(self, query: str) -> RewriteResult:
        if not query.strip():
            return RewriteResult(query=query, rewritten=False, reason="empty")

        prompt = self._prompts.render("retrieval/query_rewrite", question=query)
        start_time = time.perf_counter()

        timeout_seconds = self._settings.retrieval_query_rewrite_timeout_seconds
        try:
            rewritten = await asyncio.wait_for(
                self._call_llm(prompt), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning("Query rewrite 超时", extra={"timeout": timeout_seconds})
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="timeout",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning("Query rewrite 调用失败", extra={"error": str(exc)})
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="error",
                latency_ms=latency_ms,
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        rewritten = (rewritten or "").strip()
        if not rewritten:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="empty_output",
                latency_ms=latency_ms,
            )

        return RewriteResult(
            query=rewritten,
            rewritten=rewritten != query,
            reason=None,
            latency_ms=latency_ms,
        )

    async def _call_llm(self, prompt: str) -> str:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=self._settings.llm_model,
            api_key=self._settings.llm_api_key,
            base_url=self._settings.llm_base_url.rstrip("/"),
        )
        model = model.bind(max_tokens=self._settings.retrieval_query_rewrite_max_tokens)

        def _run() -> object:
            return model.invoke([HumanMessage(content=prompt)])

        result = await asyncio.to_thread(_run)
        return getattr(result, "content", "") or ""
