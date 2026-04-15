"""KB Chat agentic 预处理节点（MergeContext → HyDE）。

这些节点当前刻意保持最小实现：
- 优先采用安全的空操作或启发式行为
- 将重提示词的 LLM 行为延后到后续任务处理
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, cast

from langgraph.runtime import Runtime
from langgraph.types import Command

from app.core.memory_store import StoreManager
from app.core.settings import Settings
from app.services.query_rewrite_service import (
    COMPLEXITY_CLASSIFY_DECISION_VERSION,
    QueryRewriteService,
)
from app.agents.kb_chat_agentic_state import (
    DecompositionInput,
    GenerateVariantsInput,
    HydeInput,
    QueryPlanInput,
)

from .budget import now_iso
from .preprocess_context_nodes import (
    ambiguity_check,
    coref_rewrite,
    merge_context,
    normalize_rewrite,
)
from .preprocess_plan_execution import (
    _build_query_plan_finalize_update,
    _complexity_level_for_strategy,
    _default_decomposition_plan,
    _resolve_query_plan_next_node,
    _resolve_query_plan_original_query,
    decomposition,
    generate_variants,
    hyde,
    query_plan_finalize,
)
from .preprocess_query_bundle import (
    StateView,
    _complexity_cache_key,
    _extract_user_input,
    _merge_stage_summary,
    _read_complexity_cache as _read_complexity_cache_impl,
    _write_complexity_cache,
    score_query_item_quality,
)

__all__ = [
    "ambiguity_check",
    "coref_rewrite",
    "decomposition",
    "generate_variants",
    "hyde",
    "merge_context",
    "normalize_rewrite",
    "query_plan",
    "query_plan_finalize",
    "run_query_plan_scheme_b",
    "score_query_item_quality",
]


def _complexity_cache_store_status(
    runtime: Runtime[Any] | None,
) -> str | None:
    if runtime is None or runtime.store is None:
        return None
    try:
        status = StoreManager.status()
    except Exception:
        return None
    if not bool(status.get("degraded")):
        return None
    effective_backend = str(status.get("effective_backend") or "").strip().lower()
    if effective_backend != "memory":
        return None
    return "degraded_inmemory_store"


async def _read_complexity_cache(
    *,
    state: StateView,
    runtime: Runtime[Any] | None,
    cache_key: str,
) -> dict[str, Any] | None:
    return await _read_complexity_cache_impl(
        state=state,
        runtime=runtime,
        cache_key=cache_key,
    )


async def _classify_query_strategy(
    *,
    state: StateView,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    query = _resolve_query_plan_original_query(state)
    if not query:
        normalized_query = state.get("normalized_query")
        if isinstance(normalized_query, str) and normalized_query.strip():
            query = normalized_query.strip()
    if not query:
        query = _extract_user_input(state)

    strategy = "direct"
    success = False
    reasoning: str | None = None
    failure_reason: str | None = None
    confidence = 0.0
    risk_flags: list[str] = []
    decision_version = COMPLEXITY_CLASSIFY_DECISION_VERSION
    cache_hit = False
    cache_status = "disabled"
    cache_key_version = "v2"
    normalized_meta = state.get("normalized_meta")
    if not isinstance(normalized_meta, dict):
        normalized_meta = {}
    recall_risk = str(normalized_meta.get("recall_risk") or "unknown")
    has_multi_target = bool(normalized_meta.get("has_multi_target"))
    is_comparison = bool(normalized_meta.get("is_comparison"))
    cache_enabled = bool(getattr(settings, "kb_chat_complexity_cache_enabled", True))
    degraded_cache_status = _complexity_cache_store_status(runtime)
    cache_key = _complexity_cache_key(
        query=query,
        recall_risk=recall_risk,
        has_multi_target=has_multi_target,
        is_comparison=is_comparison,
        decision_version=decision_version,
        cache_key_version=cache_key_version,
    )
    if cache_enabled:
        if runtime is None or runtime.store is None:
            cache_status = "no_store"
        else:
            if degraded_cache_status is not None:
                cache_status = degraded_cache_status
            try:
                cached = await _read_complexity_cache(
                    state=state,
                    runtime=runtime,
                    cache_key=cache_key,
                )
            except Exception:  # pragma: no cover
                cached = None
                cache_status = "read_error"
            if isinstance(cached, dict):
                candidate_strategy = (
                    str(cached.get("strategy") or "direct").strip().lower()
                )
                strategy = (
                    candidate_strategy
                    if candidate_strategy in {"direct", "decomposition", "multi_query"}
                    else "direct"
                )
                success = bool(cached.get("success"))
                reasoning = str(cached.get("reasoning") or "").strip() or None
                confidence = round(
                    max(0.0, min(1.0, float(cached.get("confidence") or 0.0))),
                    4,
                )
                failure_reason = None
                decision_version = (
                    str(
                        cached.get("decision_version")
                        or COMPLEXITY_CLASSIFY_DECISION_VERSION
                    ).strip()
                    or COMPLEXITY_CLASSIFY_DECISION_VERSION
                )
                cached_risk_flags = cached.get("risk_flags")
                raw_flags = (
                    cached_risk_flags if isinstance(cached_risk_flags, list) else []
                )
                risk_flags = [
                    str(flag).strip()
                    for flag in raw_flags
                    if isinstance(flag, str) and flag.strip()
                ][:8]
                cache_hit = True
                if degraded_cache_status is None:
                    cache_status = "hit"
            elif cache_status not in {"read_error", "degraded_inmemory_store"}:
                cache_status = "miss"

    if not cache_hit:
        try:
            svc = QueryRewriteService(settings=settings)
            decision = await svc.classify_complexity(
                query,
                recall_risk=recall_risk,
                has_multi_target=has_multi_target,
                is_comparison=is_comparison,
            )
            strategy = (
                decision.strategy
                if decision.strategy in {"direct", "decomposition", "multi_query"}
                else "direct"
            )
            success = decision.success
            reasoning = decision.reasoning
            failure_reason = getattr(decision, "failure_reason", None)
            confidence = round(max(0.0, min(1.0, float(decision.confidence or 0.0))), 4)
            decision_version = str(
                decision.decision_version or COMPLEXITY_CLASSIFY_DECISION_VERSION
            ).strip()
            if not decision_version:
                decision_version = COMPLEXITY_CLASSIFY_DECISION_VERSION
            raw_flags = (
                decision.risk_flags if isinstance(decision.risk_flags, list) else []
            )
            risk_flags = [
                str(flag).strip()
                for flag in raw_flags
                if isinstance(flag, str) and flag.strip()
            ][:8]
        except Exception:  # pragma: no cover
            strategy = "direct"
            success = False
            reasoning = None
            failure_reason = "error"
        if cache_enabled and success:
            try:
                await _write_complexity_cache(
                    state=state,
                    runtime=runtime,
                    cache_key=cache_key,
                    ttl_seconds=max(
                        0,
                        int(
                            getattr(
                                settings, "kb_chat_complexity_cache_ttl_seconds", 120
                            )
                        ),
                    ),
                    payload={
                        "strategy": strategy,
                        "success": success,
                        "reasoning": reasoning,
                        "confidence": confidence,
                        "risk_flags": risk_flags,
                        "decision_version": decision_version,
                    },
                )
                if cache_status == "miss":
                    cache_status = "write_through"
            except Exception:  # pragma: no cover
                if cache_status in {"miss", "no_store", "disabled"}:
                    cache_status = "write_error"

    return {
        "strategy": strategy,
        "success": success,
        "reasoning": reasoning,
        "failure_reason": failure_reason,
        "confidence": confidence,
        "risk_flags": risk_flags,
        "decision_version": decision_version,
        "recall_risk": recall_risk,
        "has_multi_target": has_multi_target,
        "is_comparison": is_comparison,
        "cache_hit": cache_hit,
        "cache_status": cache_status,
        "cache_key_version": cache_key_version,
    }


async def query_plan(
    state: QueryPlanInput,
    runtime: Runtime[Any],
    settings: Settings,
) -> Command[str]:
    """对问题复杂度分类，并路由到实时 Scheme B 增强链路。"""

    start = time.perf_counter()
    decision = await _classify_query_strategy(
        state=state,
        settings=settings,
        runtime=runtime,
    )
    strategy = str(decision.get("strategy") or "direct")
    next_node = _resolve_query_plan_next_node(strategy=strategy, settings=settings)
    stage_summaries = _merge_stage_summary(
        state,
        "query_plan",
        {
            "strategy": strategy,
            "confidence": float(decision.get("confidence") or 0.0),
            "risk_flags": decision.get("risk_flags") or [],
            "decision_version": decision.get("decision_version"),
            "recall_risk": decision.get("recall_risk"),
            "has_multi_target": decision.get("has_multi_target"),
            "is_comparison": decision.get("is_comparison"),
            "reasoning": decision.get("reasoning"),
            "failure_reason": decision.get("failure_reason"),
            "success": bool(decision.get("success")),
            "next_node": next_node,
            "cache_hit": bool(decision.get("cache_hit")),
            "complexity_cache_status": decision.get("cache_status"),
            "cache_key_version": decision.get("cache_key_version"),
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "completed_at": now_iso(),
        },
        settings=settings,
    )
    normalized = state.get("normalized_query")
    normalized_query = normalized.strip() if isinstance(normalized, str) else ""
    updates: dict[str, Any] = {
        "query_strategy": strategy,
        "complexity_level": _complexity_level_for_strategy(strategy),
        "query_strategy_confidence": float(decision.get("confidence") or 0.0),
        "query_strategy_signals": decision.get("risk_flags") or [],
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": [],
        "decomposition_plan": _default_decomposition_plan(normalized_query),
        "query_items": [],
        "query_plan_result": {},
        "query_plan_diagnostics": {},
        "stage_summaries": stage_summaries,
    }
    return Command(update=updates, goto=next_node)



def _merge_query_plan_state(
    base: dict[str, Any], patch: dict[str, Any]
) -> dict[str, Any]:
    merged = {**base, **patch}
    for key in ("stage_summaries", "routing_decisions", "reflection"):
        base_value = base.get(key)
        patch_value = patch.get(key)
        if isinstance(base_value, dict) and isinstance(patch_value, dict):
            merged[key] = {**base_value, **patch_value}
    return merged


def _command_update_payload(result: Command[str] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, Command):
        return result.update if isinstance(result.update, dict) else {}
    return result if isinstance(result, dict) else {}


def _command_goto(result: Command[str] | dict[str, Any]) -> str | None:
    if isinstance(result, Command):
        goto = result.goto
        return goto if isinstance(goto, str) and goto.strip() else None
    return None


async def run_query_plan_scheme_b(
    state: dict[str, Any],
    *,
    runtime: Runtime[Any] | None,
    settings: Settings,
) -> dict[str, Any]:
    """用与预处理阶段一致的实时 Scheme B 语义重建查询规划。"""

    effective_runtime = runtime
    if effective_runtime is None:
        effective_runtime = SimpleNamespace(context={}, store=None)

    current_state = dict(state)
    accumulated_updates: dict[str, Any] = {}
    effective_runtime_typed = cast(Runtime[Any], effective_runtime)

    decision = await query_plan(
        cast(QueryPlanInput, current_state),
        runtime=effective_runtime_typed,
        settings=settings,
    )
    decision_updates = _command_update_payload(decision)
    accumulated_updates = _merge_query_plan_state(accumulated_updates, decision_updates)
    current_state = _merge_query_plan_state(current_state, decision_updates)
    next_node = _command_goto(decision) or "query_plan_finalize"

    while next_node in {"decomposition", "generate_variants", "hyde"}:
        if next_node == "decomposition":
            step_result = await decomposition(
                cast(DecompositionInput, current_state), settings=settings
            )
        elif next_node == "generate_variants":
            step_result = await generate_variants(
                cast(GenerateVariantsInput, current_state), settings=settings
            )
        else:
            step_result = await hyde(cast(HydeInput, current_state), settings=settings)

        step_updates = _command_update_payload(step_result)
        accumulated_updates = _merge_query_plan_state(accumulated_updates, step_updates)
        current_state = _merge_query_plan_state(current_state, step_updates)
        next_node = _command_goto(step_result) or "query_plan_finalize"

    finalize_latency_ms = 0
    finalize_updates = _build_query_plan_finalize_update(
        state=current_state,
        runtime=effective_runtime_typed,
        settings=settings,
        latency_ms=finalize_latency_ms,
    )
    accumulated_updates = _merge_query_plan_state(accumulated_updates, finalize_updates)
    return accumulated_updates
