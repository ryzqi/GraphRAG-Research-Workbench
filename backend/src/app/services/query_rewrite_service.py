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

from langchain.agents import create_agent
from pydantic import BaseModel, ValidationError

from app.agents.kb_chat_agentic.schemas import (
    ComplexityDecision,
    DecompositionDecision,
    HyDEBatchDecision,
    MergeContextResolutionDecision,
    MultiQueryDecision,
    ReverseQuestionDecision,
    TransformQueryDecision,
)
from app.core.settings import Settings, get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.prompts import get_prompt_loader
from app.schemas.query_enhancement import QueryItem

logger = logging.getLogger(__name__)

DECOMPOSITION_MAX_SUB_QUERIES = 5
MULTI_QUERY_FIXED_VARIANTS = 3
HYDE_NUM_HYPOTHESES = 5
HYDE_AGGREGATION = "mean_embedding"
HYDE_REGENERATE_ON_RETRY = True


@dataclass(slots=True)
class RewriteResult:
    query: str
    rewritten: bool
    reason: str | None = None
    latency_ms: int | None = None
    meta: dict[str, object] | None = None


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


@dataclass(slots=True)
class ComplexityRouteResult:
    strategy: str
    success: bool
    reasoning: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class StructuredCallResult:
    payload: BaseModel | None = None
    success: bool = False
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class MergeContextResolutionResult:
    summary_text: str
    keep_memory: bool
    notes: list[str]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\\s+", " ", text).strip()


def _normalize_single_line(text: str) -> str:
    for line in text.splitlines():
        normalized = _normalize_whitespace(line)
        if normalized:
            return normalized
    return _normalize_whitespace(text)


def _sanitize_query_text(text: str) -> str:
    return _normalize_single_line(text).strip("`\"' ")


_COREF_MARKERS_ZH = [
    "这个",
    "那个",
    "这些",
    "那些",
    "它",
    "他",
    "她",
    "它们",
    "他们",
    "她们",
    "该",
    "其",
    "上述",
    "前者",
    "后者",
]
_COREF_MARKERS_EN = ["this", "that", "these", "those", "it", "they", "them"]
_COREF_MARKERS = sorted([*_COREF_MARKERS_ZH, *_COREF_MARKERS_EN], key=len, reverse=True)
_COREF_CONFIDENCE_THRESHOLD = 0.72


def _sanitize_reverse_question(text: str) -> str:
    value = _normalize_single_line(text).strip("`\"' ")
    if not value:
        return ""
    if value.endswith("?"):
        return f"{value[:-1]}？"
    if value.endswith("？"):
        return value
    return f"{value.rstrip('。.!！')}？"


def _strip_list_prefix(text: str) -> str:
    return re.sub(r"^\s*(?:[-*]+|\d+[.)])\s*", "", text).strip()


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


def _contains_coref_marker(query: str) -> bool:
    lowered = query.lower()
    if any(marker in lowered for marker in _COREF_MARKERS_ZH):
        return True
    return any(
        re.search(rf"\b{re.escape(marker)}\b", lowered) is not None
        for marker in _COREF_MARKERS_EN
    )


def _extract_query_focus_terms(query: str) -> set[str]:
    q = _normalize_whitespace(query)
    if not q:
        return set()
    tokens = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", q)
    focus: set[str] = set()
    for token in tokens:
        lowered = token.lower()
        if lowered in _COREF_MARKERS_EN:
            continue
        if token in _COREF_MARKERS_ZH:
            continue
        focus.add(lowered)
    return focus


def _split_candidate_segments(text: str) -> list[str]:
    raw_segments = re.split(r"[，。；、,.!?\n]+", _normalize_whitespace(text))
    normalized: list[str] = []
    for segment in raw_segments:
        value = segment.strip(" \"'“”‘’()[]{}")
        if not value:
            continue
        if len(value) < 2 or len(value) > 48:
            continue
        normalized.append(value)
    return normalized


def _apply_coref_candidate(query: str, candidate: str) -> tuple[str, str]:
    q = _normalize_whitespace(query)
    c = _normalize_whitespace(candidate)
    rewritten = q
    replaced = False
    for marker in _COREF_MARKERS:
        if marker in _COREF_MARKERS_EN:
            pattern = re.compile(rf"\b{re.escape(marker)}\b", flags=re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(marker), flags=re.IGNORECASE)
        rewritten, count = pattern.subn(c, rewritten)
        if count > 0:
            replaced = True
    rewritten = _sanitize_query_text(rewritten)
    if replaced and rewritten:
        return rewritten, "replace_marker"
    # If marker exists but not replaced (or stripped away), prefix candidate context conservatively.
    if c and c.lower() not in q.lower():
        prefixed = _sanitize_query_text(f"{c} {q}")
        if prefixed:
            return prefixed, "prefix_candidate"
    return q, "noop"


def _rule_based_multi_query_candidates(query: str) -> list[str]:
    q = _normalize_whitespace(query)
    if not q:
        return []
    return [
        q,
        f"{q} 同义词 技术术语 表达",
        f"{q} 用户视角 实际问题",
        f"{q} 专家视角 专业术语",
        f"{q} 窄范围 具体条件",
        f"{q} 广范围 全局概览",
    ]


def _coerce_fixed_multi_query_variants(
    queries: Iterable[str], *, original_query: str
) -> tuple[list[str], bool]:
    base = _dedupe_keep_order(queries)
    if len(base) >= MULTI_QUERY_FIXED_VARIANTS:
        return base[:MULTI_QUERY_FIXED_VARIANTS], False

    completed = _dedupe_keep_order(
        [*base, *_rule_based_multi_query_candidates(original_query)]
    )
    if len(completed) < MULTI_QUERY_FIXED_VARIANTS:
        for idx in range(len(completed), MULTI_QUERY_FIXED_VARIANTS):
            completed.append(f"{_normalize_whitespace(original_query)} 变体{idx + 1}")
    return completed[:MULTI_QUERY_FIXED_VARIANTS], True


def _normalize_hyde_documents(
    docs: Iterable[str], *, limit: int = HYDE_NUM_HYPOTHESES
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        value = _normalize_whitespace(_strip_list_prefix(str(doc or "")))
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
        if len(normalized) >= limit:
            break
    return normalized


def build_query_items(
    *,
    main_query: str,
    sub_queries: list[str] | None = None,
    variants: list[str] | None = None,
    hyde_doc: str | None = None,
    hyde_docs: list[str] | None = None,
    hyde_note: str | None = None,
) -> list[QueryItem]:
    """Build a unified query collection for retrieval + provenance.

    - Decomposition and multi-query are mutually exclusive; caller should enforce.
    - HyDE is included as a *dense-only* query item by default.
    - When `hyde_docs` has multiple candidates, retrieval may aggregate embeddings.
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

    hyde_candidates: list[str] = []
    if hyde_docs:
        hyde_candidates.extend([str(value) for value in hyde_docs if str(value).strip()])
    if hyde_doc:
        hyde_candidates.append(hyde_doc)
    hyde_candidates = _normalize_hyde_documents(hyde_candidates)
    if hyde_candidates:
        hyde_item: QueryItem = {
            "kind": "hyde",
            "query": hyde_candidates[0],
            "index": 0,
            "use_dense": True,
            "use_bm25": False,
            "hyde_queries": hyde_candidates,
            "hyde_aggregation": HYDE_AGGREGATION,
        }
        if hyde_note:
            hyde_item["note"] = _normalize_whitespace(hyde_note)
        items.append(hyde_item)

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
        self._structured_chat_model: object | None = None
        self._structured_agents: dict[type[BaseModel], object] = {}

    def _get_structured_chat_model(self) -> object:
        if self._structured_chat_model is None:
            self._structured_chat_model = create_chat_model(settings=self._settings)
        return self._structured_chat_model

    def _get_structured_agent(self, schema: type[BaseModel]) -> object:
        agent = self._structured_agents.get(schema)
        if agent is not None:
            return agent
        agent = create_agent(
            model=self._get_structured_chat_model(),
            tools=[],
            system_prompt="",
            response_format=schema,
        )
        self._structured_agents[schema] = agent
        return agent

    @staticmethod
    def _classify_structured_error(exc: Exception) -> str:
        name = exc.__class__.__name__
        if name == "StructuredOutputValidationError":
            return "invalid_schema"
        if name == "MultipleStructuredOutputsError":
            return "multiple_structured_outputs"
        return "error"

    async def _invoke_structured(
        self,
        *,
        agent: object,
        schema: type[BaseModel],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        _ = max_tokens
        request = {"messages": [{"role": "user", "content": user_prompt}]}
        try:
            ainvoke = getattr(agent, "ainvoke", None)
            if callable(ainvoke):
                result = await ainvoke(request)
            else:
                result = await asyncio.to_thread(agent.invoke, request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason=self._classify_structured_error(exc),
            )

        if not isinstance(result, dict):
            return StructuredCallResult(
                payload=None, success=False, reason="empty_structured_response"
            )
        structured_payload = result.get("structured_response")
        if structured_payload is None:
            return StructuredCallResult(
                payload=None, success=False, reason="empty_structured_response"
            )
        if isinstance(structured_payload, schema):
            return StructuredCallResult(payload=structured_payload, success=True)
        try:
            payload = schema.model_validate(structured_payload)
        except ValidationError:
            return StructuredCallResult(payload=None, success=False, reason="invalid_schema")
        return StructuredCallResult(payload=payload, success=True)

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
            prompt = self._prompts.render_with_few_shot(prompt_key, question=query)
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
            if timeout_value <= 0:
                rewritten = await self._call_llm(prompt, max_tokens=max_tokens_value)
            else:
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
        rewritten = _sanitize_query_text((rewritten or "").strip())
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
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ) -> RewriteResult:
        """Coreference rewrite with context-aware, low-latency heuristics."""
        _ = timeout_seconds
        start = time.perf_counter()
        q = _sanitize_query_text(query)
        if not enabled:
            return RewriteResult(
                query=q,
                rewritten=False,
                reason="disabled",
                latency_ms=0,
                meta={
                    "triggered": False,
                    "confidence": 0.0,
                    "candidate_count": 0,
                    "selected_mention": "",
                    "resolution_source": "none",
                    "needs_clarification": False,
                },
            )
        if not q:
            return RewriteResult(
                query=q,
                rewritten=False,
                reason="empty",
                latency_ms=0,
                meta={
                    "triggered": False,
                    "confidence": 0.0,
                    "candidate_count": 0,
                    "selected_mention": "",
                    "resolution_source": "none",
                    "needs_clarification": False,
                },
            )

        triggered = _contains_coref_marker(q) or len(q) <= 8
        focus_terms = _extract_query_focus_terms(q)
        candidates: list[tuple[float, str, str]] = []
        seen: set[str] = set()

        if isinstance(recent_turns, list):
            normalized_turns = [
                turn
                for turn in recent_turns
                if isinstance(turn, dict) and isinstance(turn.get("text"), str)
            ]
            total = len(normalized_turns)
            for idx, turn in enumerate(reversed(normalized_turns)):
                text = _normalize_whitespace(str(turn.get("text") or ""))
                if not text:
                    continue
                role = str(turn.get("role") or "assistant").lower()
                role_weight = 1.25 if role == "user" else 0.75
                recency_weight = max(0.0, 1.0 - (idx / max(total, 1)) * 0.45)
                for segment in _split_candidate_segments(text):
                    lowered = segment.lower()
                    if lowered in seen:
                        continue
                    overlap = 0.0
                    if focus_terms and any(term in lowered for term in focus_terms):
                        overlap = 0.3
                    length_penalty = 0.2 if len(segment) > 24 else 0.0
                    score = role_weight + recency_weight + overlap - length_penalty
                    candidates.append((score, segment, f"recent_turns_{role}"))
                    seen.add(lowered)

        for source_name, source_text, source_weight in (
            ("summary", summary_text, 0.65),
            ("memory", memory_snippet, 0.55),
        ):
            text = _normalize_whitespace(str(source_text or ""))
            if not text:
                continue
            for segment in _split_candidate_segments(text):
                lowered = segment.lower()
                if lowered in seen:
                    continue
                overlap = 0.0
                if focus_terms and any(term in lowered for term in focus_terms):
                    overlap = 0.2
                score = source_weight + overlap
                candidates.append((score, segment, source_name))
                seen.add(lowered)

        candidates.sort(key=lambda item: item[0], reverse=True)
        candidate_count = len(candidates)
        top_score, top_mention, source = (candidates[0] if candidates else (0.0, "", "none"))
        confidence = round(max(0.0, min(1.0, top_score / 2.0)), 4)
        needs_clarification = False
        reason = "no_trigger"
        rewritten_query = q
        apply_strategy = "noop"

        if not triggered:
            reason = "no_trigger"
        elif not top_mention:
            reason = "no_candidate"
            needs_clarification = True
        elif confidence < _COREF_CONFIDENCE_THRESHOLD:
            reason = "low_confidence"
            needs_clarification = True
        else:
            rewritten_query, apply_strategy = _apply_coref_candidate(q, top_mention)
            if rewritten_query != q:
                reason = None
            else:
                reason = "unchanged_after_apply"
                needs_clarification = True

        latency_ms = int((time.perf_counter() - start) * 1000)
        return RewriteResult(
            query=rewritten_query,
            rewritten=rewritten_query != q,
            reason=reason,
            latency_ms=latency_ms,
            meta={
                "triggered": triggered,
                "confidence": confidence,
                "candidate_count": candidate_count,
                "selected_mention": top_mention,
                "resolution_source": source,
                "apply_strategy": apply_strategy,
                "needs_clarification": needs_clarification,
                "clarification_hint": (
                    "请问你指的是哪一个具体对象？请补充明确名称或上下文。"
                    if needs_clarification and triggered
                    else ""
                ),
            },
        )

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

        structured_result = await self._call_prompt_structured(
            "kb_chat/reverse_question",
            schema=ReverseQuestionDecision,
            timeout_seconds=timeout_seconds,
            max_tokens=128,
            question=query,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, ReverseQuestionDecision)
            and structured_result.payload.question.strip()
        ):
            text = _sanitize_reverse_question(structured_result.payload.question.strip())
            if not text:
                text = (
                    "为了更准确地回答，你指的是哪个对象/范围？请补充具体指代或上下文。"
                )
            return TextResult(
                text=text,
                success=True,
                reason=structured_result.reason,
                latency_ms=structured_result.latency_ms,
            )

        text = "为了更准确地回答，你指的是哪个对象/范围？请补充具体指代或上下文。"
        latency_ms = int((time.perf_counter() - start) * 1000)
        return TextResult(
            text=text,
            success=True,
            reason=structured_result.reason or "default_template",
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

        structured_result = await self._call_prompt_structured(
            "kb_chat/transform_query",
            schema=TransformQueryDecision,
            timeout_seconds=timeout_seconds,
            max_tokens=96,
            question=query,
            reason=reason,
            hint=hint or "",
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, TransformQueryDecision)
            and structured_result.payload.query.strip()
        ):
            text = _sanitize_query_text(structured_result.payload.query.strip())
            return RewriteResult(
                query=text,
                rewritten=text != query,
                reason=structured_result.reason,
                latency_ms=structured_result.latency_ms,
            )

        # Reuse existing retrieval rewrite behavior as a low-risk fallback.
        fallback = await self.rewrite(query, timeout_seconds=timeout_seconds)
        # If fallback succeeded but didn't change, still keep transform surface explicit.
        if fallback.reason is None:
            fallback.reason = structured_result.reason or "fallback_rewrite"
        return fallback

    async def resolve_merge_context_conflict(
        self,
        *,
        question: str,
        summary_text: str,
        memory_snippet: str,
    ) -> MergeContextResolutionResult:
        """Resolve conflict between summary and memory content for context merge."""
        structured_result = await self._call_prompt_structured(
            "kb_chat/context_merge",
            schema=MergeContextResolutionDecision,
            timeout_seconds=0.8,
            max_tokens=192,
            question=_normalize_whitespace(question),
            summary_text=_normalize_whitespace(summary_text),
            memory_snippet=_normalize_whitespace(memory_snippet),
        )
        payload = structured_result.payload
        if (
            structured_result.success
            and isinstance(payload, MergeContextResolutionDecision)
        ):
            summary = _normalize_whitespace(payload.summary_text)
            notes = _dedupe_keep_order(
                [_normalize_whitespace(str(note)) for note in payload.notes]
            )[:4]
            return MergeContextResolutionResult(
                summary_text=summary,
                keep_memory=bool(payload.keep_memory),
                notes=notes,
                success=True,
                reason=structured_result.reason,
                latency_ms=structured_result.latency_ms,
            )

        return MergeContextResolutionResult(
            summary_text=_normalize_whitespace(summary_text),
            keep_memory=True,
            notes=[],
            success=False,
            reason=structured_result.reason or "fallback_keep_inputs",
            latency_ms=structured_result.latency_ms,
        )

    async def classify_complexity(
        self,
        query: str,
    ) -> ComplexityRouteResult:
        """Decide preprocess routing strategy."""
        start = time.perf_counter()
        q = _normalize_whitespace(query)
        if not q:
            return ComplexityRouteResult(
                strategy="direct",
                success=False,
                latency_ms=0,
            )

        structured_result = await self._call_prompt_structured(
            "kb_chat/complexity_router",
            schema=ComplexityDecision,
            timeout_seconds=None,
            max_tokens=256,
            question=q,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, ComplexityDecision)
        ):
            payload = structured_result.payload
            strategy = str(payload.strategy or "direct").strip().lower()
            if strategy not in {"direct", "decomposition", "multi_query"}:
                strategy = "direct"
            return ComplexityRouteResult(
                strategy=strategy,
                success=True,
                reasoning=getattr(payload, "reasoning", None),
                latency_ms=structured_result.latency_ms,
            )

        latency_ms = int((time.perf_counter() - start) * 1000)
        return ComplexityRouteResult(
            strategy="direct",
            success=False,
            latency_ms=latency_ms,
        )

    async def decompose(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        """Decompose query into sub-questions via structured LLM output only."""
        start = time.perf_counter()
        enabled_flag = True if enabled is None else bool(enabled)
        if not enabled_flag:
            return QueryListResult(
                queries=[], success=False, reason="disabled", latency_ms=0
            )

        q = _normalize_whitespace(query)
        if not q:
            return QueryListResult(
                queries=[], success=False, reason="empty", latency_ms=0
            )

        structured_result = await self._call_prompt_structured(
            "kb_chat/decomposition",
            schema=DecompositionDecision,
            timeout_seconds=None,
            max_tokens=256,
            question=q,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, DecompositionDecision)
        ):
            sub_queries = _dedupe_keep_order(
                structured_result.payload.sub_queries
            )[:DECOMPOSITION_MAX_SUB_QUERIES]
            if sub_queries:
                latency_ms = int((time.perf_counter() - start) * 1000)
                return QueryListResult(
                    queries=sub_queries,
                    success=True,
                    reason="llm_structured",
                    latency_ms=latency_ms,
                )

        latency_ms = int((time.perf_counter() - start) * 1000)
        fallback_reason = structured_result.reason or "llm_structured_fallback_original"
        return QueryListResult(
            queries=[q],
            success=False,
            reason=fallback_reason,
            latency_ms=latency_ms,
        )

    async def generate_variants(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        """Generate exactly 3 multi-query variants (LLM-first with safe fallback)."""
        start = time.perf_counter()
        enabled_flag = True if enabled is None else bool(enabled)
        if not enabled_flag:
            return QueryListResult(
                queries=[], success=False, reason="disabled", latency_ms=0
            )

        q = _normalize_whitespace(query)
        if not q:
            return QueryListResult(
                queries=[], success=False, reason="empty", latency_ms=0
            )

        structured_result = await self._call_prompt_structured(
            "kb_chat/multi_query",
            schema=MultiQueryDecision,
            timeout_seconds=None,
            max_tokens=256,
            question=q,
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, MultiQueryDecision)
        ):
            fixed_variants, completed = _coerce_fixed_multi_query_variants(
                structured_result.payload.queries,
                original_query=q,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            return QueryListResult(
                queries=fixed_variants,
                success=True,
                reason=(
                    "llm_structured_with_rule_completion"
                    if completed
                    else "llm_structured"
                ),
                latency_ms=latency_ms,
            )

        latency_ms = int((time.perf_counter() - start) * 1000)
        fixed_variants, _ = _coerce_fixed_multi_query_variants([], original_query=q)
        return QueryListResult(
            queries=fixed_variants,
            success=False,
            reason="llm_failed_rule_completion",
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
    ) -> QueryListResult:
        """HyDE generator (LLM-first with safe fallback)."""
        start = time.perf_counter()
        enabled_flag = (
            bool(self._settings.kb_chat_hyde_enabled)
            if enabled is None
            else bool(enabled)
        )
        if not enabled_flag:
            return QueryListResult(queries=[], success=False, reason="disabled", latency_ms=0)

        q = _normalize_whitespace(query)
        if not q:
            return QueryListResult(queries=[], success=False, reason="empty", latency_ms=0)

        structured_result = await self._call_prompt_structured(
            "kb_chat/hyde",
            schema=HyDEBatchDecision,
            timeout_seconds=None,
            max_tokens=768,
            question=q,
            num_hypotheses=HYDE_NUM_HYPOTHESES,
        )
        if structured_result.success and isinstance(
            structured_result.payload, HyDEBatchDecision
        ):
            docs = _normalize_hyde_documents(
                structured_result.payload.hypothetical_documents,
                limit=HYDE_NUM_HYPOTHESES,
            )
            if docs:
                latency_ms = int((time.perf_counter() - start) * 1000)
                return QueryListResult(
                    queries=docs,
                    success=True,
                    reason="llm_structured",
                    latency_ms=latency_ms,
                )

        latency_ms = int((time.perf_counter() - start) * 1000)
        return QueryListResult(
            queries=[],
            success=False,
            reason="llm_failed_fallback_empty",
            latency_ms=latency_ms,
        )

    def _is_ambiguous_heuristic(self, query: str) -> bool:
        q = _normalize_whitespace(query)
        if not q:
            return True
        if len(q) <= 2:
            return True
        # Only trigger when the query is *short* and contains coref-like markers,
        # to avoid false positives for normal descriptive questions.
        if len(q) <= 10 and _contains_coref_marker(q):
            return True
        if len(q) <= 6 and ("怎么" in q or "咋" in q or "如何" in q):
            return True
        return False

    async def _call_prompt_structured(
        self,
        prompt_key: str,
        *,
        schema: type[BaseModel],
        timeout_seconds: float | None,
        max_tokens: int,
        **kwargs: object,
    ) -> StructuredCallResult:
        """Call prompt and parse structured output via create_agent(response_format=Schema)."""
        try:
            prompt = self._prompts.render_with_few_shot(prompt_key, **kwargs)
        except KeyError:
            return StructuredCallResult(
                payload=None, success=False, reason="prompt_missing", latency_ms=0
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "Prompt render 失败",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return StructuredCallResult(
                payload=None, success=False, reason="prompt_error", latency_ms=0
            )

        start_time = time.perf_counter()
        timeout_value = (
            float(self._settings.retrieval_query_rewrite_timeout_seconds)
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        agent = self._get_structured_agent(schema)
        try:
            if timeout_value <= 0:
                structured = await self._invoke_structured(
                    agent=agent,
                    schema=schema,
                    user_prompt=prompt,
                    max_tokens=max_tokens,
                )
            else:
                structured = await asyncio.wait_for(
                    self._invoke_structured(
                        agent=agent,
                        schema=schema,
                        user_prompt=prompt,
                        max_tokens=max_tokens,
                    ),
                    timeout=timeout_value,
                )
        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(
                "Prompt LLM structured 超时",
                extra={"prompt_key": prompt_key, "timeout": timeout_value},
            )
            return StructuredCallResult(
                payload=None, success=False, reason="timeout", latency_ms=latency_ms
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(
                "Prompt LLM structured 调用失败",
                extra={"prompt_key": prompt_key, "error": str(exc)},
            )
            return StructuredCallResult(
                payload=None, success=False, reason="error", latency_ms=latency_ms
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        if not structured.success or structured.payload is None:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason=structured.reason or "invalid_schema",
                latency_ms=latency_ms,
            )
        return StructuredCallResult(
            payload=structured.payload,
            success=True,
            reason=structured.reason,
            latency_ms=latency_ms,
        )

    async def _call_llm(self, prompt: str, *, max_tokens: int) -> str:
        from langchain.messages import HumanMessage

        model = create_chat_model(settings=self._settings)
        model = model.bind(max_tokens=max_tokens)

        def _run() -> object:
            return model.invoke([HumanMessage(content=prompt)])

        result = await asyncio.to_thread(_run)
        return getattr(result, "content", "") or ""
