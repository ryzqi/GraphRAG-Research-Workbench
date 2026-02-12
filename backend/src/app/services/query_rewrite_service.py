"""Query enhancement service (rewrite / clarify / fanout helpers).

This module is shared by:
- RetrievalService's optional single-query rewrite
- KB Chat agentic preprocess (coref/normalize/ambiguity/decompose/multi-query/HyDE)

Keep outputs JSON-friendly so they can be safely stored in LangGraph state.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Iterable

from app.core.settings import Settings, get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
from app.prompts import get_prompt_loader
from app.schemas.query_enhancement import QueryItem

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RewriteResult:
    query: str
    rewritten: bool
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class TextResult:
    text: str
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class QueryListResult:
    queries: list[str]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class AmbiguityResult:
    ambiguous: bool
    reverse_question: str | None = None
    reason: str | None = None
    latency_ms: int | None = None


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\\s+", " ", text).strip()


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = _normalize_whitespace(item)
        if not value or value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def build_query_items(
    *,
    main_query: str,
    sub_queries: list[str] | None = None,
    variants: list[str] | None = None,
    hyde_doc: str | None = None,
) -> list[QueryItem]:
    """Build a unified query collection for retrieval + provenance.

    - Decomposition and multi-query are mutually exclusive; caller should enforce.
    - HyDE is included as a *dense-only* query item by default.
    """

    main = _normalize_whitespace(main_query)
    if not main:
        return []

    items: list[QueryItem] = [
        {
            "kind": "main",
            "query": main,
            "use_dense": True,
            "use_bm25": True,
        }
    ]

    if sub_queries:
        for idx, q in enumerate(sub_queries):
            qn = _normalize_whitespace(q)
            if qn:
                items.append(
                    {
                        "kind": "subquery",
                        "query": qn,
                        "index": idx,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )
    elif variants:
        for idx, q in enumerate(variants):
            qn = _normalize_whitespace(q)
            if qn:
                items.append(
                    {
                        "kind": "variant",
                        "query": qn,
                        "index": idx,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )

    if hyde_doc:
        hd = _normalize_whitespace(hyde_doc)
        if hd:
            items.append(
                {
                    "kind": "hyde",
                    "query": hd,
                    "index": 0,
                    "use_dense": True,
                    "use_bm25": False,
                }
            )

    # Global dedupe to avoid repeated retrieval calls. Keep first occurrence.
    deduped: list[QueryItem] = []
    seen: set[tuple[str, bool, bool]] = set()
    for item in items:
        query = item.get("query") or ""
        use_dense = bool(item.get("use_dense", True))
        use_bm25 = bool(item.get("use_bm25", True))
        key = (query, use_dense, use_bm25)
        if query and key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


class QueryRewriteService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._prompts = get_prompt_loader()

    async def rewrite(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        prompt_key: str = "retrieval/query_rewrite",
    ) -> RewriteResult:
        if not query.strip():
            return RewriteResult(query=query, rewritten=False, reason="empty")

        try:
            prompt = self._prompts.render(prompt_key, question=query)
        except KeyError:
            return RewriteResult(query=query, rewritten=False, reason="prompt_missing")
        start_time = time.perf_counter()

        timeout_value = (
            float(self._settings.retrieval_query_rewrite_timeout_seconds)
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        max_tokens_value = (
            int(self._settings.retrieval_query_rewrite_max_tokens)
            if max_tokens is None
            else int(max_tokens)
        )
        try:
            rewritten = await asyncio.wait_for(
                self._call_llm(prompt, max_tokens=max_tokens_value),
                timeout=timeout_value,
            )
        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning("Query rewrite 超时", extra={"timeout": timeout_value})
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="timeout",
                latency_ms=latency_ms,
            )
        except asyncio.CancelledError:
            raise
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

    async def coref_rewrite(
        self,
        query: str,
        *,
        enabled: bool = True,
        timeout_seconds: float | None = None,
    ) -> RewriteResult:
        """Coreference rewrite (currently reuses generic retrieval rewrite)."""
        if not enabled:
            return RewriteResult(
                query=query, rewritten=False, reason="disabled", latency_ms=0
            )
        return await self.rewrite(query, timeout_seconds=timeout_seconds)

    async def normalize_rewrite(self, query: str) -> RewriteResult:
        """Normalize query (fast, non-LLM by default)."""
        start = time.perf_counter()
        if not query.strip():
            return RewriteResult(
                query=query, rewritten=False, reason="empty", latency_ms=0
            )

        normalized = _normalize_whitespace(query)
        latency_ms = int((time.perf_counter() - start) * 1000)
        if not normalized:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="empty_output",
                latency_ms=latency_ms,
            )

        return RewriteResult(
            query=normalized,
            rewritten=normalized != query,
            reason=None,
            latency_ms=latency_ms,
        )

    async def ambiguity_check(
        self,
        query: str,
        *,
        enabled: bool | None = None,
        timeout_seconds: float | None = None,
    ) -> AmbiguityResult:
        """Ambiguity check with safe fallback (heuristic-first)."""
        start = time.perf_counter()
        enabled_flag = (
            bool(self._settings.kb_chat_ambiguity_check_enabled)
            if enabled is None
            else bool(enabled)
        )
        if not enabled_flag:
            return AmbiguityResult(ambiguous=False, reason="disabled", latency_ms=0)

        ambiguous = self._is_ambiguous_heuristic(query)
        reverse_question: str | None = None
        reason: str | None = "heuristic"
        if ambiguous:
            rq = await self.generate_reverse_question(
                query, timeout_seconds=timeout_seconds
            )
            reverse_question = rq.text or None
            reason = rq.reason or reason
            if not reverse_question:
                reverse_question = (
                    "为了更准确地回答，你指的是哪个对象/范围？请补充具体指代或上下文。"
                )
                reason = "fallback_default_reverse_question"

        latency_ms = int((time.perf_counter() - start) * 1000)
        return AmbiguityResult(
            ambiguous=ambiguous,
            reverse_question=reverse_question,
            reason=reason,
            latency_ms=latency_ms,
        )

    async def generate_reverse_question(
        self, query: str, *, timeout_seconds: float | None = None
    ) -> TextResult:
        """Generate a clarifying question (degrades to a fixed safe template)."""
        start = time.perf_counter()

        # Follow-up task 1.11 will add prompt templates; keep a safe fallback now.
        llm_result = await self._call_prompt_text(
            "kb_chat/reverse_question",
            timeout_seconds=timeout_seconds,
            max_tokens=128,
            question=query,
        )
        if llm_result.success and llm_result.text.strip():
            return llm_result

        text = "为了更准确地回答，你指的是哪个对象/范围？请补充具体指代或上下文。"
        latency_ms = int((time.perf_counter() - start) * 1000)
        return TextResult(
            text=text,
            success=True,
            reason=llm_result.reason or "default_template",
            latency_ms=latency_ms,
        )

    async def transform_query(
        self,
        query: str,
        *,
        reason: str,
        hint: str | None = None,
        timeout_seconds: float | None = None,
        enabled: bool = True,
    ) -> RewriteResult:
        """Transform query for retry (rewrite/expand), with safe fallback."""
        if not enabled:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="disabled",
                latency_ms=0,
            )

        start = time.perf_counter()
        llm_result = await self._call_prompt_text(
            "kb_chat/transform_query",
            timeout_seconds=timeout_seconds,
            max_tokens=96,
            question=query,
            reason=reason,
            hint=hint or "",
        )
        if llm_result.success and llm_result.text.strip():
            latency_ms = int((time.perf_counter() - start) * 1000)
            text = llm_result.text.strip()
            return RewriteResult(
                query=text,
                rewritten=text != query,
                reason=llm_result.reason,
                latency_ms=latency_ms,
            )

        # Reuse existing retrieval rewrite behavior as a low-risk fallback.
        fallback = await self.rewrite(query, timeout_seconds=timeout_seconds)
        # If fallback succeeded but didn't change, still keep transform surface explicit.
        if fallback.reason is None:
            fallback.reason = llm_result.reason or "fallback_rewrite"
        return fallback

    async def decompose(
        self,
        query: str,
        *,
        enabled: bool | None = None,
        max_sub_questions: int | None = None,
    ) -> QueryListResult:
        """Decompose query into sub-questions (heuristic-first)."""
        start = time.perf_counter()
        enabled_flag = (
            bool(self._settings.kb_chat_decomposition_enabled)
            if enabled is None
            else bool(enabled)
        )
        if not enabled_flag:
            return QueryListResult(
                queries=[], success=False, reason="disabled", latency_ms=0
            )

        q = _normalize_whitespace(query)
        if not q:
            return QueryListResult(
                queries=[], success=False, reason="empty", latency_ms=0
            )

        # Split by obvious separators; keep it conservative.
        parts = [p.strip() for p in re.split(r"[；;\\n]+", q) if p.strip()]
        if not parts:
            parts = [q]

        max_n = int(
            max_sub_questions or self._settings.kb_chat_decomposition_max_sub_questions
        )
        sub_queries = parts[: max(max_n, 1)]
        latency_ms = int((time.perf_counter() - start) * 1000)
        return QueryListResult(
            queries=sub_queries,
            success=True,
            reason="heuristic",
            latency_ms=latency_ms,
        )

    async def generate_variants(
        self,
        query: str,
        *,
        enabled: bool | None = None,
        max_variants: int | None = None,
    ) -> QueryListResult:
        """Generate multi-query variants (heuristic-first)."""
        start = time.perf_counter()
        enabled_flag = (
            bool(self._settings.kb_chat_multi_query_enabled)
            if enabled is None
            else bool(enabled)
        )
        if not enabled_flag:
            return QueryListResult(
                queries=[], success=False, reason="disabled", latency_ms=0
            )

        q = _normalize_whitespace(query)
        if not q:
            return QueryListResult(
                queries=[], success=False, reason="empty", latency_ms=0
            )

        variants: list[str] = [q]
        if "是什么" not in q:
            variants.append(f"{q} 是什么")
        if "定义" not in q:
            variants.append(f"{q} 定义")

        deduped = _dedupe_keep_order(variants)
        max_n = int(max_variants or self._settings.kb_chat_multi_query_max_variants)
        deduped = deduped[: max(max_n, 1)]

        latency_ms = int((time.perf_counter() - start) * 1000)
        return QueryListResult(
            queries=deduped,
            success=True,
            reason="heuristic",
            latency_ms=latency_ms,
        )

    async def entity_expand(self, queries: list[str]) -> QueryListResult:
        """Entity expansion (placeholder, safe no-op)."""
        start = time.perf_counter()
        deduped = _dedupe_keep_order(queries)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return QueryListResult(
            queries=deduped,
            success=False,
            reason="no_op",
            latency_ms=latency_ms,
        )

    async def hyde(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> TextResult:
        """HyDE generator (placeholder; creates a short synthetic snippet)."""
        start = time.perf_counter()
        enabled_flag = (
            bool(self._settings.kb_chat_hyde_enabled)
            if enabled is None
            else bool(enabled)
        )
        if not enabled_flag:
            return TextResult(text="", success=False, reason="disabled", latency_ms=0)

        q = _normalize_whitespace(query)
        if not q:
            return TextResult(text="", success=False, reason="empty", latency_ms=0)

        # Default to a single HyDE doc for main query; keep short.
        hyde_doc = f"（HyDE）假设性说明：{q}"
        latency_ms = int((time.perf_counter() - start) * 1000)
        return TextResult(
            text=hyde_doc,
            success=True,
            reason="placeholder",
            latency_ms=latency_ms,
        )

    def _is_ambiguous_heuristic(self, query: str) -> bool:
        q = _normalize_whitespace(query)
        if not q:
            return True
        if len(q) <= 2:
            return True
        # Very conservative heuristic for Chinese pronoun/coref.
        ambiguous_markers = [
            "这个",
            "那个",
            "这些",
            "那些",
            "它",
            "他",
            "她",
            "他们",
            "她们",
            "它们",
            "上面",
            "前面",
            "刚才",
            "之前",
        ]
        # Only trigger when the query is *short* and contains coref-like markers,
        # to avoid false positives for normal descriptive questions.
        if len(q) <= 8 and any(m in q for m in ambiguous_markers):
            return True
        return False

    async def _call_prompt_text(
        self,
        prompt_key: str,
        *,
        timeout_seconds: float | None,
        max_tokens: int,
        **kwargs: object,
    ) -> TextResult:
        """Call an optional prompt template and return text (with timeout + degrade)."""
        try:
            prompt = self._prompts.render(prompt_key, **kwargs)
        except KeyError:
            return TextResult(
                text="", success=False, reason="prompt_missing", latency_ms=0
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Prompt render 失败",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return TextResult(
                text="", success=False, reason="prompt_error", latency_ms=0
            )

        start_time = time.perf_counter()
        timeout_value = (
            float(self._settings.retrieval_query_rewrite_timeout_seconds)
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        try:
            text = await asyncio.wait_for(
                self._call_llm(prompt, max_tokens=max_tokens), timeout=timeout_value
            )
        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(
                "Prompt LLM 超时",
                extra={"prompt_key": prompt_key, "timeout": timeout_value},
            )
            return TextResult(
                text="", success=False, reason="timeout", latency_ms=latency_ms
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(
                "Prompt LLM 调用失败",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return TextResult(
                text="", success=False, reason="error", latency_ms=latency_ms
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        text = (text or "").strip()
        if not text:
            return TextResult(
                text="",
                success=False,
                reason="empty_output",
                latency_ms=latency_ms,
            )
        return TextResult(text=text, success=True, reason=None, latency_ms=latency_ms)

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
