"""KB Chat preprocess 查询规划执行节点。"""

from __future__ import annotations

import time
from typing import Any

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.agents.kb_chat_agentic_state import (
    DecompositionInput,
    GenerateVariantsInput,
    HydeInput,
    QueryPlanFinalizeInput,
    merge_routing_decision,
)
from app.core.settings import Settings
from app.services.query_rewrite_service import QueryRewriteService
from app.services.query_rewrite_text import _hyde_num_hypotheses

from .budget import now_iso
from .json_safety import ensure_json_safe
from .preprocess_query_bundle import (
    StateView,
    _as_dict,
    _extract_user_input,
    _is_direct_stable_overview_query,
    _merge_stage_summary,
    _resolve_prepare_strategy,
    build_prepared_query_bundle,
    resolve_prepare_budget,
)


def _default_decomposition_plan(query: str = "") -> dict[str, Any]:
    normalized = query.strip()
    return {
        "strategy": "direct",
        "version": "kb_chat_decomposition_plan_v2",
        "sub_query_specs": [
            {
                "query": normalized,
                "priority": 1,
                "coverage_tags": [],
                "purpose": "canonical",
            }
        ]
        if normalized
        else [],
        "risk_flags": [],
        "reasoning": "",
    }


def _resolve_query_plan_next_node(*, strategy: str, settings: Settings) -> str:
    if strategy == "decomposition":
        if bool(getattr(settings, "kb_chat_decomposition_enabled", True)):
            return "decomposition"
        if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
            return "generate_variants"
        return "hyde"
    if strategy == "multi_query":
        if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
            return "generate_variants"
        return "hyde"
    return "hyde"


def _complexity_level_for_strategy(strategy: str) -> str:
    if strategy == "decomposition":
        return "complex"
    if strategy == "multi_query":
        return "moderate"
    return "simple"



async def decomposition(state: DecompositionInput, settings: Settings) -> Command[str]:
    """生成子查询（经 QueryRewriteService，安全降级）。"""
    start = time.perf_counter()
    query = state.get("normalized_query")
    if not isinstance(query, str) or not query.strip():
        query = _extract_user_input(state)

    sub_queries: list[str] = []
    success = False
    reason: str | None = None
    decomposition_plan: dict[str, Any] = {
        "strategy": "direct",
        "version": "kb_chat_decomposition_plan_v2",
        "sub_query_specs": [],
        "risk_flags": [],
        "reasoning": "",
    }
    diagnostics: dict[str, Any] = {}
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.decompose(query)
        sub_queries = result.queries
        success = result.success
        reason = result.reason
        if isinstance(result.plan, dict):
            decomposition_plan = result.plan
        if isinstance(result.diagnostics, dict):
            diagnostics = result.diagnostics
    except Exception:  # pragma: no cover
        sub_queries = [query.strip()] if query.strip() else []
        success = False
        reason = "error"
        decomposition_plan = {
            "strategy": "direct",
            "version": "kb_chat_decomposition_plan_v2",
            "sub_query_specs": [
                {
                    "query": query.strip(),
                    "priority": 1,
                    "coverage_tags": [],
                    "purpose": "exception_fallback",
                }
            ]
            if query.strip()
            else [],
            "risk_flags": ["error_fallback"],
            "reasoning": "error",
        }

    stage_summaries = _merge_stage_summary(
        state,
        "decomposition",
        {
            "driver": "llm",
            "count": len(sub_queries),
            "success": success,
            "reason": reason,
            "strategy": decomposition_plan.get("strategy"),
            "version": decomposition_plan.get("version"),
            "risk_flags": decomposition_plan.get("risk_flags"),
            "diagnostics": diagnostics,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )

    stage_summaries["decomposition"]["next_node"] = "hyde"
    return Command(
        update={
            "sub_queries": sub_queries,
            "decomposition_plan": decomposition_plan,
            "stage_summaries": stage_summaries,
        },
        goto="hyde",
    )


async def generate_variants(
    state: GenerateVariantsInput,
    settings: Settings,
) -> Command[str]:
    """生成查询变体（经 QueryRewriteService，安全降级）。"""
    start = time.perf_counter()
    query = _resolve_query_plan_original_query(state)
    if not query:
        normalized_query = state.get("normalized_query")
        if isinstance(normalized_query, str) and normalized_query.strip():
            query = normalized_query.strip()
    if not query:
        query = _extract_user_input(state)
    deduped: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.generate_variants(query)
        deduped = result.queries
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        deduped = [query.strip()] if query.strip() else []
        success = False
        reason = "error"

    stage_summaries = _merge_stage_summary(
        state,
        "generate_variants",
        {
            "driver": "llm",
            "count": len(deduped),
            "alias_count": 0,
            "success": success,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    stage_summaries["generate_variants"]["next_node"] = "hyde"
    return Command(
        update={"multi_queries": deduped, "stage_summaries": stage_summaries},
        goto="hyde",
    )


async def hyde(state: HydeInput, settings: Settings) -> dict[str, Any]:
    """HyDE 节点（LLM 驱动，带安全兜底）。"""
    start = time.perf_counter()
    query = _resolve_query_plan_normalized_query(state)
    original_query = _resolve_query_plan_original_query(state) or query
    strategy = _resolve_prepare_strategy(state)
    if _is_direct_stable_overview_query(
        original_query=original_query,
        normalized_query=query,
        strategy=strategy,
    ):
        stage_summaries = _merge_stage_summary(
            state,
            "hyde",
            {
                "driver": "rule",
                "success": True,
                "requested_count": 0,
                "generated_count": 0,
                "retry_regenerated": False,
                "reason": "stable_overview_direct_skip_hyde",
                "completed_at": now_iso(),
                "latency_ms": int((time.perf_counter() - start) * 1000),
            },
            settings=settings,
        )
        return {"hyde_docs": [], "stage_summaries": stage_summaries}
    hyde_docs: list[str] = []
    success = False
    reason: str | None = None
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.hyde(query)
        hyde_docs = [
            item for item in result.queries if isinstance(item, str) and item.strip()
        ]
        success = result.success
        reason = result.reason
    except Exception:  # pragma: no cover
        hyde_docs = []
        success = False
        reason = "error"
    loop_counts = state.get("loop_counts")
    retry_regenerated = (
        isinstance(loop_counts, dict)
        and int(loop_counts.get("retrieval_retries") or 0) > 0
    )

    stage_summaries = _merge_stage_summary(
        state,
        "hyde",
        {
            "driver": "llm",
            "success": success,
            "requested_count": _hyde_num_hypotheses(),
            "generated_count": len(hyde_docs),
            "retry_regenerated": retry_regenerated,
            "reason": reason,
            "completed_at": now_iso(),
            "latency_ms": int((time.perf_counter() - start) * 1000),
        },
        settings=settings,
    )
    return {"hyde_docs": hyde_docs, "stage_summaries": stage_summaries}


def _resolve_query_plan_original_query(state: StateView) -> str:
    original_query = state.get("resolved_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = state.get("coref_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = state.get("rewrite_input_query")
    if not isinstance(original_query, str) or not original_query.strip():
        original_query = _extract_user_input(state)
    return original_query.strip()


def _resolve_query_plan_normalized_query(state: StateView) -> str:
    normalized = state.get("normalized_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = state.get("resolved_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = state.get("coref_query")
    if not isinstance(normalized, str) or not normalized.strip():
        normalized = _extract_user_input(state)
    return normalized.strip()


def _build_query_plan_fallback_policy(
    *,
    strategy: str,
    normalized_meta: dict[str, Any],
    settings: Settings,
    stable_overview: bool = False,
) -> dict[str, bool]:
    recall_risk = str(normalized_meta.get("recall_risk") or "medium").strip().lower()
    allow_broaden = strategy in {"decomposition", "multi_query"} or recall_risk in {
        "medium",
        "high",
    }
    return {
        "allow_broaden": allow_broaden,
        "allow_hyde": not (strategy == "direct" and stable_overview),
        "allow_retry_rewrite": True,
    }


def _build_query_plan_finalize_update(
    *,
    state: StateView,
    runtime: Runtime[Any],
    settings: Settings,
    latency_ms: int,
) -> dict[str, Any]:
    normalized = _resolve_query_plan_normalized_query(state)
    original_query = _resolve_query_plan_original_query(state) or normalized
    stable_overview = _is_direct_stable_overview_query(
        original_query=original_query,
        normalized_query=normalized,
        strategy=_resolve_prepare_strategy(state),
    )
    normalized_meta = _as_dict(state.get("normalized_meta")) or {}
    sub_queries_raw = state.get("sub_queries")
    if not isinstance(sub_queries_raw, list):
        sub_queries_raw = []
    sub_queries = [q for q in sub_queries_raw if isinstance(q, str) and q.strip()]

    decomposition_plan = state.get("decomposition_plan")
    if not isinstance(decomposition_plan, dict):
        decomposition_plan = {}
    sub_query_specs_raw = decomposition_plan.get("sub_query_specs")
    if not isinstance(sub_query_specs_raw, list):
        sub_query_specs_raw = []
    sub_query_specs = [spec for spec in sub_query_specs_raw if isinstance(spec, dict)]

    multi_queries_raw = state.get("multi_queries")
    if not isinstance(multi_queries_raw, list):
        multi_queries_raw = []
    multi_queries = [
        query for query in multi_queries_raw if isinstance(query, str) and query.strip()
    ]

    hyde_docs_raw = state.get("hyde_docs")
    if not isinstance(hyde_docs_raw, list):
        hyde_docs_raw = []
    hyde_docs = [doc for doc in hyde_docs_raw if isinstance(doc, str) and doc.strip()]

    strategy = _resolve_prepare_strategy(state)
    budget = resolve_prepare_budget(state=state, runtime=runtime, settings=settings)
    bundle = build_prepared_query_bundle(
        original_query=original_query,
        normalized_query=normalized,
        strategy=strategy,
        sub_queries=sub_queries,
        sub_query_specs=sub_query_specs,
        multi_queries=multi_queries,
        hyde_docs=hyde_docs,
        normalized_meta=normalized_meta,
        budget=budget,
    )
    prepare_diagnostics = {
        **(_as_dict(bundle.get("prepare_diagnostics")) or {}),
        "timing": {"latency_ms": latency_ms},
    }
    message_plan = _as_dict(bundle.get("message_plan")) or {}
    query_bundle = _as_dict(bundle.get("query_bundle")) or {}
    raw_query_items = bundle.get("query_items")
    query_items: list[Any] = raw_query_items if isinstance(raw_query_items, list) else []
    fallback_reason = str(prepare_diagnostics.get("fallback_reason") or "").strip()
    if fallback_reason.lower() == "none":
        fallback_reason = ""
    dedup_stats = _as_dict(query_bundle.get("dedup_stats")) or {}
    stage_summaries_state = _as_dict(state.get("stage_summaries")) or {}
    query_plan_summary = _as_dict(stage_summaries_state.get("query_plan")) or {}
    raw_candidates = message_plan.get("candidates")
    candidates: list[Any] = raw_candidates if isinstance(raw_candidates, list) else []
    quality_signals = (
        prepare_diagnostics.get("quality_signals")
        if isinstance(prepare_diagnostics.get("quality_signals"), list)
        else []
    )
    kind_breakdown = _as_dict(query_bundle.get("kind_breakdown")) or {}
    rejection_counts = {
        "fragment_rejected": 0,
        "duplicate_rejected": int(dedup_stats.get("duplicate_dropped") or 0),
        "low_quality_rejected": int(dedup_stats.get("low_quality_dropped") or 0),
        "over_budget_rejected": sum(
            1
            for item in message_plan.get("dropped") or []
            if isinstance(item, dict) and str(item.get("reason") or "") == "over_budget"
        ),
    }
    query_plan_result = ensure_json_safe(
        {
            "strategy": strategy,
            "reasoning": str(query_plan_summary.get("reasoning") or ""),
            "fallback_policy": _build_query_plan_fallback_policy(
                strategy=strategy,
                normalized_meta=normalized_meta,
                settings=settings,
                stable_overview=stable_overview,
            ),
        },
        settings=settings,
        label="query_plan_result",
    )
    query_plan_diagnostics_payload = ensure_json_safe(
        {
            "candidate_count": len(candidates),
            "selected_count": len(query_items),
            "fallback_reason": fallback_reason,
            "latency_ms": latency_ms,
            "rejection_counts": rejection_counts,
            "quality_signals": quality_signals,
            "kind_breakdown": kind_breakdown,
            "budget": _as_dict(message_plan.get("budget")) or budget,
        },
        settings=settings,
        label="query_plan_diagnostics",
    )
    query_plan_diagnostics = _as_dict(query_plan_diagnostics_payload) or {}
    safe_query_items = ensure_json_safe(
        query_items, settings=settings, label="query_items"
    )
    stage_summaries = _merge_stage_summary(
        state,
        "query_plan_finalize",
        {
            "strategy": strategy,
            "query_count": len(query_items),
            "candidate_count": len(candidates),
            "selected_count": len(query_items),
            "rejection_counts": query_plan_diagnostics.get("rejection_counts") or {},
            "fallback_reason": fallback_reason or None,
            "kind_breakdown": kind_breakdown,
            "latency_ms": latency_ms,
            "completed_at": now_iso(),
        },
        settings=settings,
    )
    return {
        "query_strategy": strategy,
        "query_plan_result": query_plan_result,
        "query_plan_diagnostics": query_plan_diagnostics_payload,
        "query_items": safe_query_items,
        "stage_summaries": stage_summaries,
    }


async def query_plan_finalize(
    state: QueryPlanFinalizeInput,
    runtime: Runtime[Any],
    settings: Settings,
) -> Command[str]:
    """将 Scheme B 查询规划定稿为可直接检索的 query_items。"""

    start = time.perf_counter()
    update = _build_query_plan_finalize_update(
        state=state,
        runtime=runtime,
        settings=settings,
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    fallback_reason = str(
        update["query_plan_diagnostics"].get("fallback_reason") or "none"
    )
    outer_next_node = "retrieval_subgraph"
    action = "none"
    reason = "query_planned"
    reason_code = "query_planned"
    if fallback_reason != "none":
        outer_next_node = "transform_query"
        action = "transform_query"
        reason = fallback_reason
        reason_code = fallback_reason
        reflection = _as_dict(state.get("reflection")) or {}
        update["reflection"] = {
            **reflection,
            "action": "transform_query",
            "reason": fallback_reason,
        }
    update = {
        **update,
        **merge_routing_decision(
            state,
            "preprocess",
            {
                "phase": "preprocess",
                "next_node": outer_next_node,
                "action": action,
                "reason": reason,
                "reason_code": reason_code,
                "decision_source": "query_plan_finalize",
                "completed_at": now_iso(),
            },
            updates=update,
        ),
    }
    return Command(update=update, goto="preprocess_exit")


