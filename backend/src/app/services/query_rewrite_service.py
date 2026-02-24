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
    AmbiguityDecision,
    ClarificationSlotDecision,
    ComplexityDecision,
    DecompositionDecision,
    HyDEBatchDecision,
    MergeContextResolutionDecision,
    MultiQueryDecision,
    NormalizeDecision,
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
    plan: dict[str, object] | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(slots=True)
class AmbiguityResult:
    ambiguous: bool
    reverse_question: str | None = None
    reason: str | None = None
    latency_ms: int | None = None
    reason_code: str | None = None
    confidence: float | None = None
    model_reason: str | None = None
    fallback_used: bool = False
    clarification_payload: dict[str, object] | None = None


@dataclass(slots=True)
class ComplexityRouteResult:
    strategy: str
    success: bool
    reasoning: str | None = None
    confidence: float = 0.0
    risk_flags: list[str] | None = None
    decision_version: str | None = None
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
    "他们",
    "她们",
    "它们",
    "上面",
    "前面",
    "刚才",
]
_COREF_MARKERS_EN = ["this", "that", "these", "those", "it", "they", "them"]
_COREF_MARKERS = sorted([*_COREF_MARKERS_ZH, *_COREF_MARKERS_EN], key=len, reverse=True)
_COREF_CONFIDENCE_THRESHOLD = 0.72
_DEFAULT_CLARIFICATION_QUESTION = (
    "为了更准确地回答，请补充你指的是哪个对象、范围或时间？"
)
_REASON_CODES = {
    "missing_entity",
    "missing_scope",
    "missing_time",
    "missing_metric",
    "coref_uncertain",
    "mixed",
}

_ACRONYM_ALIAS_MAP: dict[str, str] = {
    "k8s": "kubernetes",
    "oauth2": "oauth 2.0",
    "oauth": "oauth 2.0",
    "sla": "service level agreement",
    "api": "application programming interface",
    "sdk": "software development kit",
}
_COMPARE_KEYWORDS = (
    "compare",
    "difference",
    "vs",
    "which",
    "better",
    "优缺点",
    "区别",
    "对比",
    "比较",
)
_MULTI_TARGET_SEPARATORS = (",", "，", " and ", " 与 ", " 和 ", "及")


def _normalize_reason_code(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _REASON_CODES:
            return normalized
    return "mixed"


def _normalize_clarification_options(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _sanitize_query_text(str(value or ""))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        normalized.append(text)
        seen.add(key)
        if len(normalized) >= 6:
            break
    return normalized


def _build_clarification_payload(
    *,
    question: str,
    reason_code: str,
    confidence: float,
    model_reason: str | None,
    slots: Iterable[ClarificationSlotDecision] | None = None,
    suggested_answers: Iterable[str] | None = None,
) -> dict[str, object]:
    payload_slots: list[dict[str, object]] = []
    for slot in slots or []:
        key = _sanitize_query_text(slot.key)
        label = _sanitize_query_text(slot.label)
        if not key or not label:
            continue
        payload_slots.append(
            {
                "key": key,
                "label": label,
                "required": bool(slot.required),
                "options": _normalize_clarification_options(slot.options),
            }
        )
    return {
        "question": question,
        "reason_code": reason_code,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "model_reason": _normalize_whitespace(model_reason or ""),
        "slots": payload_slots,
        "suggested_answers": _normalize_clarification_options(suggested_answers or []),
    }


def _sanitize_aliases(aliases: Iterable[str], *, limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        value = _sanitize_query_text(str(alias or ""))
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        deduped.append(value)
        seen.add(key)
        if len(deduped) >= limit:
            break
    return deduped


def _sanitize_risk_flags(values: Iterable[object], *, limit: int = 8) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalize_whitespace(str(value or ""))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        normalized.append(text[:64])
        seen.add(key)
        if len(normalized) >= limit:
            break
    return normalized


def _extract_number_tokens(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def _extract_time_constraints(text: str) -> list[str]:
    patterns = (
        r"\b\d{4}\b",
        r"\b\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?\b",
        r"\d{4}年(?:\d{1,2}月(?:\d{1,2}日)?)?",
        r"(?:Q[1-4]|[1-4]季度)",
    )
    values: list[str] = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    return _sanitize_aliases(values, limit=6)


def _extract_metric_constraints(text: str) -> list[str]:
    metric_tokens = (
        "SLA",
        "latency",
        "error rate",
        "availability",
        "throughput",
        "p95",
        "p99",
        "可用性",
        "错误率",
        "延迟",
        "吞吐",
        "指标",
    )
    lowered = text.lower()
    found = [token for token in metric_tokens if token.lower() in lowered]
    return _sanitize_aliases(found, limit=6)


def _extract_scope_constraints(text: str) -> list[str]:
    scopes = (
        "生产环境",
        "测试环境",
        "线上",
        "离线",
        "global",
        "regional",
        "国内",
        "海外",
    )
    lowered = text.lower()
    found = [token for token in scopes if token.lower() in lowered]
    return _sanitize_aliases(found, limit=6)


def _infer_recall_risk(*, query: str, alias_count: int) -> str:
    lowered = query.lower()
    has_mixed = bool(re.search(r"[A-Za-z]", query) and re.search(r"[\u4e00-\u9fff]", query))
    acronym_hits = sum(1 for token in _ACRONYM_ALIAS_MAP if re.search(rf"\b{re.escape(token)}\b", lowered))
    if alias_count >= 3 or has_mixed or acronym_hits >= 2:
        return "high"
    if alias_count >= 1 or acronym_hits >= 1:
        return "medium"
    return "low"


def _looks_compare_or_multi_target(query: str) -> bool:
    lowered = query.lower()
    if any(keyword in lowered for keyword in _COMPARE_KEYWORDS):
        return True
    return any(separator in query for separator in _MULTI_TARGET_SEPARATORS)


def _rule_normalize_query(query: str, *, alias_limit: int) -> tuple[str, dict[str, object]]:
    text = _sanitize_query_text(query)
    if not text:
        return "", {
            "aliases": [],
            "entities": [],
            "time_constraints": [],
            "metric_constraints": [],
            "scope_constraints": [],
            "recall_risk": "low",
            "drift_risk": False,
            "constraint_preserved": True,
            "has_multi_target": False,
            "is_comparison": False,
            "reasoning": "empty_input",
        }

    text = re.sub(r"[\u3000\t\r\n]+", " ", text)
    text = re.sub(r"[，、;；|]+", " ", text)
    text = _normalize_whitespace(text)

    aliases: list[str] = []
    lowered = f" {text.lower()} "
    for acronym, expansion in _ACRONYM_ALIAS_MAP.items():
        if f" {acronym} " in lowered:
            aliases.append(expansion)

    entities = _sanitize_aliases(sorted(_extract_query_focus_terms(text)), limit=8)
    time_constraints = _extract_time_constraints(text)
    metric_constraints = _extract_metric_constraints(text)
    scope_constraints = _extract_scope_constraints(text)
    aliases = _sanitize_aliases([*aliases, *entities[:2]], limit=alias_limit)

    recall_risk = _infer_recall_risk(query=text, alias_count=len(aliases))
    normalized_meta: dict[str, object] = {
        "aliases": aliases,
        "entities": entities,
        "time_constraints": time_constraints,
        "metric_constraints": metric_constraints,
        "scope_constraints": scope_constraints,
        "recall_risk": recall_risk,
        "drift_risk": False,
        "constraint_preserved": True,
        "has_multi_target": _looks_compare_or_multi_target(text),
        "is_comparison": any(keyword in text.lower() for keyword in _COMPARE_KEYWORDS),
        "reasoning": "rule_based_normalization",
    }
    return text, normalized_meta


def _sanitize_reverse_question(text: str) -> str:
    value = _normalize_single_line(text).strip("`\"' ")
    if not value:
        return ""
    if value.endswith("?"):
        value = value[:-1].rstrip()
    if value.endswith("？"):
        return value
    return f"{value.rstrip('。.!?,，；;')}？"



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
    raw_segments = re.split(r"[，。；、,.!?;:\n]+", _normalize_whitespace(text))
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
    sub_query_specs: list[dict[str, object]] | None = None,
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
        specs_by_query: dict[str, dict[str, object]] = {}
        for spec in sub_query_specs or []:
            if not isinstance(spec, dict):
                continue
            query_value = _normalize_whitespace(str(spec.get("query") or ""))
            if not query_value:
                continue
            specs_by_query.setdefault(query_value.casefold(), spec)
        for idx, q in enumerate(sub_queries):
            qn = _normalize_whitespace(q)
            if qn:
                spec = specs_by_query.get(qn.casefold()) or {}
                raw_tags = (
                    spec.get("coverage_tags")
                    if isinstance(spec.get("coverage_tags"), list)
                    else []
                )
                coverage_tags = [
                    _normalize_whitespace(str(tag))
                    for tag in raw_tags
                    if _normalize_whitespace(str(tag))
                ][:6]
                priority = spec.get("priority")
                if not isinstance(priority, int):
                    priority = idx + 1
                purpose = _normalize_whitespace(str(spec.get("purpose") or ""))
                items.append(
                    {
                        "kind": "subquery",
                        "query": qn,
                        "index": idx,
                        "origin": "decomposition",
                        "subquery_id": f"sq_{idx + 1}",
                        "priority": max(1, min(int(priority), 8)),
                        "coverage_tags": coverage_tags,
                        "purpose": purpose,
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
                    _DEFAULT_CLARIFICATION_QUESTION
                    if needs_clarification and triggered
                    else ""
                ),
            },
        )

    async def normalize_rewrite(
        self,
        query: str,
        *,
        llm_enabled: bool | None = None,
        alias_limit: int | None = None,
        timeout_seconds: float | None = None,
    ) -> RewriteResult:
        """Normalize query with rule-first logic and optional structured LLM refinement."""
        start = time.perf_counter()
        if not query.strip():
            return RewriteResult(
                query=query, rewritten=False, reason="empty", latency_ms=0
            )

        alias_max = max(1, min(8, int(alias_limit or getattr(self._settings, "kb_chat_normalize_alias_max", 4))))
        rule_query, rule_meta = _rule_normalize_query(query, alias_limit=alias_max)
        if not rule_query:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="empty_output",
                latency_ms=latency_ms,
                meta={
                    **rule_meta,
                    "source": "rule_only",
                    "fallback_reason": "empty_rule_output",
                },
            )

        enabled_flag = (
            bool(getattr(self._settings, "kb_chat_normalize_llm_enabled", True))
            if llm_enabled is None
            else bool(llm_enabled)
        )
        if not enabled_flag:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return RewriteResult(
                query=rule_query,
                rewritten=rule_query != query,
                reason="llm_disabled",
                latency_ms=latency_ms,
                meta={**rule_meta, "source": "rule_only", "fallback_reason": "llm_disabled"},
            )

        llm_timeout = (
            float(getattr(self._settings, "kb_chat_normalize_timeout_seconds", 0.8))
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        structured_result = await self._call_prompt_structured(
            "kb_chat/normalize_query",
            schema=NormalizeDecision,
            timeout_seconds=llm_timeout,
            max_tokens=320,
            question=query,
            rule_normalized_query=rule_query,
            alias_limit=alias_max,
        )
        fallback_reason = structured_result.reason
        if structured_result.success and isinstance(structured_result.payload, NormalizeDecision):
            payload = structured_result.payload
            candidate_query = _sanitize_query_text(payload.canonical_query)
            if candidate_query:
                original_numbers = _extract_number_tokens(rule_query)
                candidate_numbers = _extract_number_tokens(candidate_query)
                constraint_preserved = original_numbers.issubset(candidate_numbers)
                aliases = _sanitize_aliases(
                    [
                        *payload.aliases,
                        *(
                            rule_meta.get("aliases", [])
                            if isinstance(rule_meta.get("aliases"), list)
                            else []
                        ),
                    ],
                    limit=alias_max,
                )
                entities = _sanitize_aliases(
                    [
                        *payload.entities,
                        *(
                            rule_meta.get("entities", [])
                            if isinstance(rule_meta.get("entities"), list)
                            else []
                        ),
                    ],
                    limit=8,
                )
                time_constraints = _sanitize_aliases(
                    [
                        *payload.time_constraints,
                        *(
                            rule_meta.get("time_constraints", [])
                            if isinstance(rule_meta.get("time_constraints"), list)
                            else []
                        ),
                    ],
                    limit=6,
                )
                metric_constraints = _sanitize_aliases(
                    [
                        *payload.metric_constraints,
                        *(
                            rule_meta.get("metric_constraints", [])
                            if isinstance(rule_meta.get("metric_constraints"), list)
                            else []
                        ),
                    ],
                    limit=6,
                )
                scope_constraints = _sanitize_aliases(
                    [
                        *payload.scope_constraints,
                        *(
                            rule_meta.get("scope_constraints", [])
                            if isinstance(rule_meta.get("scope_constraints"), list)
                            else []
                        ),
                    ],
                    limit=6,
                )
                recall_risk = payload.recall_risk
                if recall_risk not in {"low", "medium", "high"}:
                    recall_risk = str(rule_meta.get("recall_risk") or "medium")

                if constraint_preserved:
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    return RewriteResult(
                        query=candidate_query,
                        rewritten=candidate_query != query,
                        reason="llm_structured",
                        latency_ms=latency_ms,
                        meta={
                            "source": "llm_structured",
                            "fallback_reason": "",
                            "aliases": aliases,
                            "entities": entities,
                            "time_constraints": time_constraints,
                            "metric_constraints": metric_constraints,
                            "scope_constraints": scope_constraints,
                            "recall_risk": recall_risk,
                            "drift_risk": bool(payload.drift_risk),
                            "constraint_preserved": True,
                            "has_multi_target": bool(rule_meta.get("has_multi_target")),
                            "is_comparison": bool(rule_meta.get("is_comparison")),
                            "reasoning": _normalize_whitespace(payload.reasoning or ""),
                        },
                    )
                fallback_reason = "constraint_not_preserved"

        latency_ms = int((time.perf_counter() - start) * 1000)
        return RewriteResult(
            query=rule_query,
            rewritten=rule_query != query,
            reason="rule_fallback",
            latency_ms=latency_ms,
            meta={
                **rule_meta,
                "source": "rule_fallback",
                "fallback_reason": fallback_reason or "llm_unavailable",
            },
        )

    async def ambiguity_check(
        self,
        query: str,
        *,
        enabled: bool | None = None,
        timeout_seconds: float | None = None,
        coref_meta: dict[str, object] | None = None,
    ) -> AmbiguityResult:
        """Model-driven ambiguity decision with guardrail fallback."""
        start = time.perf_counter()
        enabled_flag = (
            bool(self._settings.kb_chat_ambiguity_check_enabled)
            if enabled is None
            else bool(enabled)
        )
        if not enabled_flag:
            return AmbiguityResult(ambiguous=False, reason="disabled", latency_ms=0)

        q = _sanitize_query_text(query)
        if not q:
            payload = _build_clarification_payload(
                question=_DEFAULT_CLARIFICATION_QUESTION,
                reason_code="missing_entity",
                confidence=1.0,
                model_reason="empty_query_guardrail",
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            return AmbiguityResult(
                ambiguous=True,
                reverse_question=str(payload["question"]),
                reason="guardrail_empty_query",
                latency_ms=latency_ms,
                reason_code="missing_entity",
                confidence=1.0,
                model_reason="empty_query_guardrail",
                fallback_used=True,
                clarification_payload=payload,
            )

        coref_confidence = 0.0
        coref_hint = ""
        coref_selected_mention = ""
        coref_needs_clarification = False
        if isinstance(coref_meta, dict):
            confidence_value = coref_meta.get("confidence")
            if isinstance(confidence_value, (int, float)):
                coref_confidence = float(confidence_value)
            hint_value = coref_meta.get("clarification_hint")
            if isinstance(hint_value, str):
                coref_hint = _normalize_whitespace(hint_value)
            mention_value = coref_meta.get("selected_mention")
            if isinstance(mention_value, str):
                coref_selected_mention = _normalize_whitespace(mention_value)
            coref_needs_clarification = bool(coref_meta.get("needs_clarification"))

        structured_result = await self._call_prompt_structured(
            "kb_chat/ambiguity_decision",
            schema=AmbiguityDecision,
            timeout_seconds=timeout_seconds,
            max_tokens=320,
            question=q,
            coref_confidence=round(max(0.0, min(1.0, coref_confidence)), 4),
            coref_hint=coref_hint,
            coref_selected_mention=coref_selected_mention,
            coref_needs_clarification=coref_needs_clarification,
        )

        fallback_used = False
        ambiguous = False
        reason = structured_result.reason or "model_structured"
        reason_code = "mixed"
        confidence = 0.0
        model_reason = ""
        reverse_question: str | None = None
        clarification_payload: dict[str, object] | None = None

        if structured_result.success and isinstance(
            structured_result.payload, AmbiguityDecision
        ):
            payload = structured_result.payload
            ambiguous = bool(payload.ambiguous)
            reason_code = _normalize_reason_code(payload.reason_code)
            confidence = round(max(0.0, min(1.0, float(payload.confidence))), 4)
            model_reason = _normalize_whitespace(payload.reasoning or "")
            if ambiguous:
                question_text = _sanitize_reverse_question(
                    payload.clarifying_question or ""
                )
                if not question_text:
                    question_text = _DEFAULT_CLARIFICATION_QUESTION
                clarification_payload = _build_clarification_payload(
                    question=question_text,
                    reason_code=reason_code,
                    confidence=confidence,
                    model_reason=model_reason,
                    slots=payload.missing_slots,
                    suggested_answers=payload.suggested_answers,
                )
                reverse_question = str(clarification_payload.get("question") or "")
        else:
            fallback_used = True
            ambiguous = self._is_ambiguous_heuristic(q)
            if ambiguous:
                reason_code = (
                    "coref_uncertain" if coref_needs_clarification else "mixed"
                )
                confidence = 0.35
                model_reason = "guardrail_fallback"
                clarification_payload = _build_clarification_payload(
                    question=_DEFAULT_CLARIFICATION_QUESTION,
                    reason_code=reason_code,
                    confidence=confidence,
                    model_reason=model_reason,
                )
                reverse_question = str(clarification_payload.get("question") or "")
            reason = structured_result.reason or "model_failed_guardrail_fallback"

        latency_ms = int((time.perf_counter() - start) * 1000)
        return AmbiguityResult(
            ambiguous=ambiguous,
            reverse_question=reverse_question,
            reason=reason,
            latency_ms=latency_ms,
            reason_code=reason_code if ambiguous else None,
            confidence=confidence if ambiguous else None,
            model_reason=model_reason or None,
            fallback_used=fallback_used,
            clarification_payload=clarification_payload if ambiguous else None,
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
                text = _DEFAULT_CLARIFICATION_QUESTION
            return TextResult(
                text=text,
                success=True,
                reason=structured_result.reason,
                latency_ms=structured_result.latency_ms,
            )

        text = _DEFAULT_CLARIFICATION_QUESTION
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
        *,
        recall_risk: str | None = None,
        has_multi_target: bool = False,
        is_comparison: bool = False,
        timeout_seconds: float | None = None,
    ) -> ComplexityRouteResult:
        """Decide preprocess routing strategy."""
        start = time.perf_counter()
        q = _normalize_whitespace(query)
        if not q:
            return ComplexityRouteResult(
                strategy="direct",
                success=False,
                confidence=0.0,
                risk_flags=[],
                decision_version="kb_chat_complexity_router_v4",
                latency_ms=0,
            )

        structured_result = await self._call_prompt_structured(
            "kb_chat/complexity_router",
            schema=ComplexityDecision,
            timeout_seconds=timeout_seconds,
            max_tokens=256,
            question=q,
            recall_risk=(recall_risk or "unknown"),
            has_multi_target=bool(has_multi_target),
            is_comparison=bool(is_comparison),
        )
        if (
            structured_result.success
            and isinstance(structured_result.payload, ComplexityDecision)
        ):
            payload = structured_result.payload
            strategy = str(payload.strategy or "direct").strip().lower()
            if strategy not in {"direct", "decomposition", "multi_query"}:
                strategy = "direct"
            confidence = round(max(0.0, min(1.0, float(payload.confidence))), 4)
            risk_flags = _sanitize_risk_flags(payload.risk_flags)
            decision_version = _normalize_whitespace(payload.decision_version)
            if not decision_version:
                decision_version = "kb_chat_complexity_router_v4"
            return ComplexityRouteResult(
                strategy=strategy,
                success=True,
                reasoning=getattr(payload, "reasoning", None),
                confidence=confidence,
                risk_flags=risk_flags,
                decision_version=decision_version,
                latency_ms=structured_result.latency_ms,
            )

        latency_ms = int((time.perf_counter() - start) * 1000)
        return ComplexityRouteResult(
            strategy="direct",
            success=False,
            confidence=0.0,
            risk_flags=["llm_failed_fallback_direct"],
            decision_version="kb_chat_complexity_router_v4",
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
            payload = structured_result.payload
            spec_queries = [
                _normalize_whitespace(str(spec.get("query") or ""))
                for spec in payload.sub_query_specs
                if isinstance(spec, dict)
            ]
            sub_queries = _dedupe_keep_order(
                [*spec_queries, *payload.sub_queries]
            )[:DECOMPOSITION_MAX_SUB_QUERIES]
            if sub_queries:
                latency_ms = int((time.perf_counter() - start) * 1000)
                normalized_specs: list[dict[str, object]] = []
                for idx, q in enumerate(sub_queries):
                    matched = next(
                        (
                            spec
                            for spec in payload.sub_query_specs
                            if isinstance(spec, dict)
                            and _normalize_whitespace(str(spec.get("query") or ""))
                            == q
                        ),
                        None,
                    )
                    if isinstance(matched, dict):
                        raw_tags = (
                            matched.get("coverage_tags")
                            if isinstance(matched.get("coverage_tags"), list)
                            else []
                        )
                        tags = [
                            _normalize_whitespace(str(tag))
                            for tag in raw_tags
                            if _normalize_whitespace(str(tag))
                        ][:6]
                        raw_priority = matched.get("priority")
                        priority = (
                            int(raw_priority)
                            if isinstance(raw_priority, int)
                            else idx + 1
                        )
                        purpose = _normalize_whitespace(
                            str(matched.get("purpose") or "")
                        )
                    else:
                        tags = []
                        priority = idx + 1
                        purpose = ""
                    normalized_specs.append(
                        {
                            "query": q,
                            "priority": max(1, min(priority, 8)),
                            "coverage_tags": tags,
                            "purpose": purpose,
                        }
                    )
                plan: dict[str, object] = {
                    "strategy": str(payload.strategy or "decomposition"),
                    "version": _normalize_whitespace(payload.plan_version)
                    or "kb_chat_decomposition_plan_v2",
                    "sub_query_specs": normalized_specs,
                    "risk_flags": _sanitize_risk_flags(payload.risk_flags),
                    "reasoning": _normalize_whitespace(payload.reasoning),
                }
                return QueryListResult(
                    queries=sub_queries,
                    success=True,
                    reason="llm_structured",
                    latency_ms=latency_ms,
                    plan=plan,
                    diagnostics={
                        "source": "llm_structured",
                        "spec_count": len(normalized_specs),
                    },
                )

        latency_ms = int((time.perf_counter() - start) * 1000)
        fallback_reason = structured_result.reason or "llm_structured_fallback_original"
        return QueryListResult(
            queries=[q],
            success=False,
            reason=fallback_reason,
            latency_ms=latency_ms,
            plan={
                "strategy": "direct",
                "version": "kb_chat_decomposition_plan_v2",
                "sub_query_specs": [
                    {
                        "query": q,
                        "priority": 1,
                        "coverage_tags": [],
                        "purpose": "fallback_original_query",
                    }
                ],
                "risk_flags": ["llm_fallback"],
                "reasoning": fallback_reason,
            },
            diagnostics={"source": "fallback_original"},
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
        # Guardrail only: short query + coreference markers is likely ambiguous.
        if len(q) <= 10 and _contains_coref_marker(q):
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
