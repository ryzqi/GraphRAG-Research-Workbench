from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any

from app.agents.kb_chat_agentic.schemas import QueryPlanDecision
from app.core.settings import Settings, get_settings
from app.schemas.query_enhancement import QueryItem
from app.services.kb_query_policy import (
    build_validated_query_items,
    should_enable_broadening_retry,
    should_enable_hyde,
    should_enable_retry_rewrite,
)
from app.services.query_rewrite_service import QueryRewriteService
from app.utils.text_sanitization import sanitize_visible_text


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", sanitize_visible_text(text)).strip()


def _sanitize_query_text(text: str) -> str:
    return _normalize_whitespace(text).strip("`\"' ")


def _normalize_strategy(value: object) -> str:
    strategy = _sanitize_query_text(str(value or "")).lower()
    if strategy in {"direct", "paraphrase", "decomposition"}:
        return strategy
    return "direct"


def _normalize_kind(value: object) -> str:
    kind = _sanitize_query_text(str(value or "")).lower()
    if kind in {"main", "paraphrase", "subquery", "hyde", "retry"}:
        return kind
    return "paraphrase"


def _normalize_retrieval_mode(value: object, *, kind: str) -> str:
    mode = _sanitize_query_text(str(value or "")).lower()
    if mode in {"hybrid", "dense_only"}:
        return mode
    return "dense_only" if kind == "hyde" else "hybrid"


def _normalize_string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for raw in value:
        text = _sanitize_query_text(str(raw or ""))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        items.append(text)
        seen.add(key)
        if len(items) >= limit:
            break
    return items


def _extract_ascii_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}", text)


def _stringify_constraints(normalized_meta: dict[str, Any], key: str) -> str:
    values = _normalize_string_list(normalized_meta.get(key), limit=6)
    return "；".join(values) if values else "无"


def _fallback_reason(exc: Exception) -> str:
    _ = exc
    return "prompt_failed"


@dataclass(slots=True)
class KbQueryPlannerResult:
    strategy: str
    items: list[QueryItem]
    reasoning: str
    fallback_policy: dict[str, bool]
    diagnostics: dict[str, Any]


class KbQueryPlannerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._rewrite_service = QueryRewriteService(settings=self._settings)

    async def _call_planner_prompt(
        self,
        *,
        normalized_query: str,
        normalized_meta: dict[str, object],
    ) -> dict[str, Any]:
        structured = await self._rewrite_service._call_prompt_structured(
            "kb_chat/query_plan",
            schema=QueryPlanDecision,
            max_tokens=512,
            question=normalized_query,
            normalized_query=normalized_query,
            recall_risk=_sanitize_query_text(str(normalized_meta.get("recall_risk") or "medium"))
            or "medium",
            aliases=_stringify_constraints(normalized_meta, "aliases"),
            entities=_stringify_constraints(normalized_meta, "entities"),
            time_constraints=_stringify_constraints(normalized_meta, "time_constraints"),
            metric_constraints=_stringify_constraints(normalized_meta, "metric_constraints"),
            scope_constraints=_stringify_constraints(normalized_meta, "scope_constraints"),
        )
        if structured.success and isinstance(structured.payload, QueryPlanDecision):
            return structured.payload.model_dump(mode="json")
        raise RuntimeError(str(structured.reason or "planner_prompt_failed"))

    def _normalize_planned_items(
        self,
        items: object,
    ) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(items, start=2):
            if not isinstance(raw, dict):
                continue
            kind = _normalize_kind(raw.get("kind"))
            query = _sanitize_query_text(str(raw.get("query") or ""))
            if not query:
                continue
            retrieval_mode = _normalize_retrieval_mode(raw.get("retrieval_mode"), kind=kind)
            priority = raw.get("priority")
            if not isinstance(priority, int):
                priority = index
            normalized.append(
                {
                    "kind": kind,
                    "query": query,
                    "strategy_source": _sanitize_query_text(
                        str(raw.get("strategy_source") or "planner_llm")
                    )
                    or "planner_llm",
                    "trigger_reason": _sanitize_query_text(
                        str(raw.get("trigger_reason") or "planner_candidate")
                    )
                    or "planner_candidate",
                    "semantic_complete": bool(raw.get("semantic_complete", True)),
                    "preserve_constraints": bool(raw.get("preserve_constraints", True)),
                    "retrieval_mode": retrieval_mode,
                    "priority": max(1, min(priority, 8)),
                    "purpose": _sanitize_query_text(str(raw.get("purpose") or ""))
                    or "planner expansion",
                    "coverage_tags": _normalize_string_list(raw.get("coverage_tags"), limit=6),
                    "use_dense": True,
                    "use_bm25": retrieval_mode != "dense_only",
                }
            )
        return normalized

    def _build_fail_open_candidates(
        self,
        *,
        canonical_query: str,
        normalized_meta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for alias in _normalize_string_list(normalized_meta.get("aliases"), limit=2):
            candidates.append(
                {
                    "kind": "paraphrase",
                    "query": alias,
                    "strategy_source": "lexicon",
                    "trigger_reason": "alias_fallback",
                    "retrieval_mode": "hybrid",
                    "priority": 2,
                    "purpose": "补充别名召回",
                }
            )
        if re.search(r"[\u4e00-\u9fff]", canonical_query) and re.search(r"[A-Za-z]", canonical_query):
            for token in _extract_ascii_tokens(canonical_query)[:1]:
                candidates.append(
                    {
                        "kind": "paraphrase",
                        "query": token,
                        "strategy_source": "fallback",
                        "trigger_reason": "mixed_language_guardrail",
                        "retrieval_mode": "hybrid",
                        "priority": 3,
                        "purpose": "用于验证碎片拒绝护栏",
                    }
                )
        return candidates

    def _materialize_query_items(
        self,
        *,
        canonical_query: str,
        strategy: str,
        validated_items: list[dict[str, Any]],
    ) -> list[QueryItem]:
        result: list[QueryItem] = []
        for index, raw in enumerate(validated_items, start=1):
            item = dict(raw)
            kind = _normalize_kind(item.get("kind"))
            query = _sanitize_query_text(str(item.get("query") or ""))
            if not query:
                continue
            retrieval_mode = _normalize_retrieval_mode(item.get("retrieval_mode"), kind=kind)
            priority = item.get("priority")
            if not isinstance(priority, int):
                priority = 1 if kind == "main" else index + 1
            enriched: QueryItem = {
                "kind": kind,
                "query": query,
                "index": index - 1,
                "priority": max(1, min(priority, 8)),
                "purpose": _sanitize_query_text(str(item.get("purpose") or ""))
                or ("primary retrieval" if kind == "main" else "planner expansion"),
                "strategy_source": _sanitize_query_text(
                    str(
                        item.get("strategy_source")
                        or ("canonical" if kind == "main" and query == canonical_query else "planner_llm")
                    )
                )
                or "planner_llm",
                "trigger_reason": _sanitize_query_text(
                    str(
                        item.get("trigger_reason")
                        or ("always_keep_main" if kind == "main" else "planner_candidate")
                    )
                )
                or "planner_candidate",
                "semantic_complete": bool(item.get("semantic_complete", True)),
                "preserve_constraints": bool(item.get("preserve_constraints", True)),
                "retrieval_mode": retrieval_mode,
                "coverage_tags": _normalize_string_list(item.get("coverage_tags"), limit=6),
                "quality_score": 1.0 if kind == "main" else 0.88 if kind == "paraphrase" else 0.92,
                "use_dense": True,
                "use_bm25": retrieval_mode != "dense_only",
            }
            if strategy == "decomposition" and kind == "subquery":
                enriched["quality_score"] = 0.93
            if kind == "hyde":
                enriched["quality_score"] = 0.74
                enriched["use_bm25"] = False
            result.append(enriched)
        return result

    def _build_fallback_policy(
        self,
        *,
        strategy: str,
        normalized_meta: dict[str, Any],
        raw_policy: object,
    ) -> dict[str, bool]:
        recall_risk = _sanitize_query_text(str(normalized_meta.get("recall_risk") or "medium")).lower()
        policy = raw_policy if isinstance(raw_policy, dict) else {}
        return {
            "allow_broaden": bool(
                policy.get("allow_broaden", should_enable_broadening_retry(first_pass_failed=True))
            ),
            "allow_hyde": bool(
                policy.get(
                    "allow_hyde",
                    should_enable_hyde(
                        strategy=strategy,
                        recall_risk=recall_risk,
                        first_pass_failed=True,
                    ),
                )
            ),
            "allow_retry_rewrite": bool(
                policy.get(
                    "allow_retry_rewrite",
                    should_enable_retry_rewrite(first_pass_failed=True),
                )
            ),
        }

    async def plan(
        self,
        *,
        normalized_query: str,
        normalized_meta: dict[str, object] | None = None,
    ) -> KbQueryPlannerResult:
        start = time.perf_counter()
        normalized_meta_dict = (
            dict(normalized_meta) if isinstance(normalized_meta, dict) else {}
        )
        canonical_query = _sanitize_query_text(normalized_query)
        if not canonical_query:
            return KbQueryPlannerResult(
                strategy="direct",
                items=[],
                reasoning="",
                fallback_policy={
                    "allow_broaden": False,
                    "allow_hyde": False,
                    "allow_retry_rewrite": False,
                },
                diagnostics={
                    "candidate_count": 0,
                    "selected_count": 0,
                    "rejection_counts": {
                        "fragment_rejected": 0,
                        "duplicate_rejected": 0,
                        "empty_rejected": 0,
                        "over_budget_rejected": 0,
                    },
                    "fallback_reason": "empty_query",
                    "latency_ms": 0,
                },
            )

        prompt_payload: dict[str, Any] = {}
        fallback_reason = "none"
        planner_enabled = bool(
            getattr(self._settings, "kb_chat_query_planner_enabled", True)
        )
        if planner_enabled:
            try:
                prompt_payload = await self._call_planner_prompt(
                    normalized_query=canonical_query,
                    normalized_meta=normalized_meta_dict,
                )
            except Exception as exc:
                fallback_reason = _fallback_reason(exc)
                prompt_payload = {}
        else:
            fallback_reason = "llm_disabled"

        strategy = _normalize_strategy(prompt_payload.get("strategy"))
        reasoning = _sanitize_query_text(str(prompt_payload.get("reasoning") or ""))
        normalized_items = self._normalize_planned_items(prompt_payload.get("items"))
        if not normalized_items:
            normalized_items = self._build_fail_open_candidates(
                canonical_query=canonical_query,
                normalized_meta=normalized_meta_dict,
            )
        validated = build_validated_query_items(
            normalized_query=canonical_query,
            planned_items=normalized_items,
        )

        items = self._materialize_query_items(
            canonical_query=canonical_query,
            strategy=strategy,
            validated_items=validated.items,
        )
        max_items = max(
            1,
            int(
                getattr(
                    self._settings,
                    "kb_chat_query_planner_max_first_pass_items",
                    3,
                )
            ),
        )
        over_budget_rejected = 0
        if len(items) > max_items:
            over_budget_rejected = len(items) - max_items
            items = items[:max_items]

        if not items:
            strategy = "direct"
            items = self._materialize_query_items(
                canonical_query=canonical_query,
                strategy="direct",
                validated_items=[{"kind": "main", "query": canonical_query}],
            )
        elif fallback_reason != "none":
            strategy = "direct"

        fallback_policy = self._build_fallback_policy(
            strategy=strategy,
            normalized_meta=normalized_meta_dict,
            raw_policy=prompt_payload.get("fallback_policy"),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        diagnostics = {
            "candidate_count": len(normalized_items) + 1,
            "selected_count": len(items),
            "rejection_counts": {
                **validated.rejections,
                "over_budget_rejected": over_budget_rejected,
            },
            "fallback_reason": fallback_reason,
            "latency_ms": latency_ms,
        }
        return KbQueryPlannerResult(
            strategy=strategy,
            items=items,
            reasoning=reasoning
            or (
                "canonical query is already retrieval-ready"
                if strategy == "direct"
                else "planner produced retrieval-ready expansions"
            ),
            fallback_policy=fallback_policy,
            diagnostics=diagnostics,
        )
