"""KB Chat agentic ReflectionLayer 节点（相关性 / 答案审查）。

设计目标：
- 保持最小实现且适合生产使用，并提供兜底
- 仅向状态写入近似 JSON 的可序列化值
- 感知预算，并将路由绑定到 loop_counts 的轮次 / 重试预算
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langgraph.runtime import Runtime

from app.agents.kb_chat_agentic_state import (
    AnswerRoutingDecisionInput,
    TransformQueryInput,
    resolve_routing_decision,
)
from app.core.settings import Settings
from app.services.query_rewrite_service import QueryRewriteService

from .budget import now_iso
from .json_safety import ensure_json_safe
from .preprocess import run_query_plan_scheme_b
from .reflection_draft_generation import generate_draft
from .reflection_draft_utils import (
    _build_answer_coverage_hint,
    _extract_question_entities,
    _extract_required_dimensions,
    _extract_required_term_map,
)
from .reflection_retrieval import (
    dispatch_subqueries,
    kb_retrieve_context,
    merge_subquery_context,
    retrieve_subquery_context,
)
from .reflection_shared import (
    _as_str,
    _get_loop_counts,
    _merge_reflection,
    _merge_stage_summary,
    _resolve_query_text,
    _set_final_answer_for_exit,
)

__all__ = [
    "_build_answer_coverage_hint",
    "_extract_question_entities",
    "_extract_required_dimensions",
    "_extract_required_term_map",
    "dispatch_subqueries",
    "generate_draft",
    "kb_retrieve_context",
    "merge_subquery_context",
    "retrieve_subquery_context",
    "route_after_answer_review",
    "transform_query_for_retry",
]


async def transform_query_for_retry(
    state: TransformQueryInput,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """改写查询并递增 retrieval_retries，同时遵守预算约束。"""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)

    loop_counts = {
        **loop_counts,
        "retrieval_retries": loop_counts["retrieval_retries"] + 1,
    }
    if loop_counts["retrieval_retries"] > int(settings.kb_chat_max_retrieval_retries):
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state,
                _as_str(state.get("draft_answer")),
                reason="max_retrieval_retries",
            ),
        }

    current = _resolve_query_text(state)
    reflection = state.get("reflection")
    reason = reflection.get("reason") if isinstance(reflection, dict) else None
    hint = reflection.get("hint") if isinstance(reflection, dict) else None

    new_query = current
    normalized_meta: dict[str, Any] = {}
    try:
        svc = QueryRewriteService(settings=settings)
        result = await svc.transform_query(
            current,
            reason=_as_str(reason) or "retry",
            hint=_as_str(hint) or None,
            enabled=True,
        )
        if result.query.strip():
            new_query = result.query.strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        new_query = current

    try:
        svc = QueryRewriteService(settings=settings)
        normalize_result = await svc.normalize_rewrite(new_query)
        if normalize_result.query.strip():
            new_query = normalize_result.query.strip()
        if isinstance(normalize_result.meta, dict):
            normalized_meta = normalize_result.meta
    except asyncio.CancelledError:
        raise
    except Exception:
        normalized_meta = {}

    original_resolved_query = _as_str(state.get("resolved_query")).strip()
    if not original_resolved_query:
        original_resolved_query = _as_str(state.get("rewrite_input_query")).strip()
    if not original_resolved_query:
        original_resolved_query = current
    original_coref_query = (
        _as_str(state.get("coref_query")).strip() or original_resolved_query
    )
    rewrite_input_query = (
        _as_str(state.get("rewrite_input_query")).strip()
        or original_resolved_query
        or new_query
    )
    reference_resolution_meta = (
        state.get("reference_resolution_meta")
        if isinstance(state.get("reference_resolution_meta"), dict)
        else {}
    )

    plan_updates = await run_query_plan_scheme_b(
        {
            **state,
            "normalized_query": new_query,
            "resolved_query": original_resolved_query or new_query,
            "rewrite_input_query": rewrite_input_query,
            "reference_resolution_meta": reference_resolution_meta,
            "normalized_meta": normalized_meta,
            "coref_query": original_coref_query or new_query,
            "stage_summaries": state.get("stage_summaries")
            if isinstance(state.get("stage_summaries"), dict)
            else {},
        },
        runtime=runtime,
        settings=settings,
    )
    query_items = ensure_json_safe(
        plan_updates.get("query_items")
        if isinstance(plan_updates.get("query_items"), list)
        else [],
        settings=settings,
        label="transform_query.query_items",
    )
    query_plan_result = ensure_json_safe(
        plan_updates.get("query_plan_result")
        if isinstance(plan_updates.get("query_plan_result"), dict)
        else {},
        settings=settings,
        label="transform_query.query_plan_result",
    )
    query_plan_diagnostics = ensure_json_safe(
        plan_updates.get("query_plan_diagnostics")
        if isinstance(plan_updates.get("query_plan_diagnostics"), dict)
        else {},
        settings=settings,
        label="transform_query.query_plan_diagnostics",
    )
    query_strategy = str(plan_updates.get("query_strategy") or "direct")
    stage_seed = {
        **state,
        "stage_summaries": plan_updates.get("stage_summaries")
        if isinstance(plan_updates.get("stage_summaries"), dict)
        else (
            state.get("stage_summaries")
            if isinstance(state.get("stage_summaries"), dict)
            else {}
        ),
    }

    return {
        "loop_counts": loop_counts,
        "normalized_query": new_query,
        "resolved_query": new_query,
        "reference_resolution_meta": {},
        "normalized_meta": normalized_meta,
        "coref_query": new_query,
        "query_strategy": query_strategy,
        "sub_queries": plan_updates.get("sub_queries")
        if isinstance(plan_updates.get("sub_queries"), list)
        else [],
        "multi_queries": plan_updates.get("multi_queries")
        if isinstance(plan_updates.get("multi_queries"), list)
        else [],
        "hyde_docs": plan_updates.get("hyde_docs")
        if isinstance(plan_updates.get("hyde_docs"), list)
        else [],
        "decomposition_plan": plan_updates.get("decomposition_plan")
        if isinstance(plan_updates.get("decomposition_plan"), dict)
        else {},
        "query_items": query_items,
        "query_plan_result": query_plan_result,
        "query_plan_diagnostics": query_plan_diagnostics,
        **_merge_reflection(
            state,
            {
                "action": "transform_query",
                "reason": _as_str(reason) or "retry",
                "hint": _as_str(hint),
            },
        ),
        **_merge_stage_summary(
            stage_seed,
            "transform_query",
            {
                "rewritten": new_query != current,
                "normalized_after_retry": True,
                "normalization_source": str(normalized_meta.get("source") or ""),
                "query_plan_strategy": query_strategy,
                "query_plan_items_count": len(query_items),
                "query_plan_fallback_reason": query_plan_diagnostics.get(
                    "fallback_reason"
                ),
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


def route_after_answer_review(
    state: AnswerRoutingDecisionInput, settings: Settings
) -> str:
    """在 AnswerReview 后路由到 END、transform_query 或 force_exit。"""
    routing = resolve_routing_decision(state, "answer_subgraph")
    next_node = _as_str(routing.get("next_node")).strip()
    if next_node in {"END", "transform_query", "force_exit"}:
        return next_node
    loop_counts = _get_loop_counts(state)
    max_total_rounds = int(getattr(settings, "kb_chat_max_total_rounds", 3))
    if loop_counts.get("total_rounds", 0) >= max_total_rounds:
        return "force_exit"
    if loop_counts["retrieval_retries"] >= int(
        getattr(settings, "kb_chat_max_retrieval_retries", 2)
    ):
        return "force_exit"
    return "transform_query"
