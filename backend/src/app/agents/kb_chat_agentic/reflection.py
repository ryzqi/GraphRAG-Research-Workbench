"""KB Chat agentic ReflectionLayer nodes (relevance / answer-review).

These nodes are designed to be:
- Minimal & production-safe (fallbacks)
- Serializable-friendly (only write JSON-ish values to state)
- Budget-aware (bind routing to loop_counts rounds/retries budgets)
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, ROUND_HALF_UP
import re
import time
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from app.core.settings import Settings, get_settings
from app.prompts import get_prompt_loader
from app.services.streaming import extract_answer_text
from app.services.query_rewrite_service import (
    HYDE_REGENERATE_ON_RETRY,
    QueryRewriteService,
    build_query_items,
)
from app.agents.kb_chat_agentic_state import (
    AnswerRoutingDecisionInput,
    ConfidenceCalibrateInput,
    DispatchSubqueriesInput,
    DocGateRoutingDecisionInput,
    FinalizeAnswerInput,
    MergeSubqueryContextInput,
    RetrieveContextInput,
    RetrieveSubqueryContextInput,
    TransformQueryInput,
    resolve_routing_decision,
)

from .budget import now_iso
from .dispatch_fuse import (
    build_retrieval_payload,
    make_send_task,
    sort_by_priority_then_index,
)
from .json_safety import ensure_json_safe
from .runtime_config import (
    normalize_alias_max,
    normalize_timeout_seconds,
    parallel_retrieval_include_main,
    parallel_retrieval_max_branches,
    parallel_retrieval_min_queries,
    retrieval_top_k,
)

_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
_CITATION_ONLY_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
}


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _get_loop_counts(state: dict) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _current_retrieval_round(state: dict) -> int:
    loop_counts = _get_loop_counts(state)
    return max(int(loop_counts.get("retrieval_retries") or 0), 0)


def _total_rounds_exceeded(loop_counts: dict[str, int], settings: Settings) -> bool:
    return loop_counts.get("total_rounds", 0) >= int(settings.kb_chat_max_total_rounds)


def _extract_evidence_count(final_context: str) -> int:
    if not final_context:
        return 0
    return sum(1 for _ in _EVIDENCE_LINE_RE.finditer(final_context))


def _resolve_subquery_specs(state: dict) -> list[dict[str, Any]]:
    plan = state.get("decomposition_plan")
    if not isinstance(plan, dict):
        return []
    specs = plan.get("sub_query_specs")
    if not isinstance(specs, list):
        return []
    return [spec for spec in specs if isinstance(spec, dict)]


def _normalize_query_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    query = _as_str(item.get("query")).strip()
    if not query:
        return None
    kind = _as_str(item.get("kind")).strip() or "other"
    normalized: dict[str, Any] = {
        "kind": kind,
        "query": query,
        "use_dense": bool(item.get("use_dense", True)),
        "use_bm25": bool(item.get("use_bm25", True)),
    }
    if isinstance(item.get("index"), int):
        normalized["index"] = int(item["index"])
    if isinstance(item.get("note"), str) and item.get("note", "").strip():
        normalized["note"] = _as_str(item.get("note")).strip()
    if isinstance(item.get("origin"), str) and item.get("origin", "").strip():
        normalized["origin"] = _as_str(item.get("origin")).strip()
    if isinstance(item.get("subquery_id"), str) and item.get("subquery_id", "").strip():
        normalized["subquery_id"] = _as_str(item.get("subquery_id")).strip()
    if isinstance(item.get("priority"), int):
        normalized["priority"] = int(item["priority"])
    if isinstance(item.get("purpose"), str) and item.get("purpose", "").strip():
        normalized["purpose"] = _as_str(item.get("purpose")).strip()
    raw_tags = item.get("coverage_tags")
    if isinstance(raw_tags, list):
        tags = [_as_str(tag).strip() for tag in raw_tags if _as_str(tag).strip()]
        if tags:
            normalized["coverage_tags"] = tags[:6]
    if kind == "hyde":
        raw_hyde_queries = item.get("hyde_queries")
        if isinstance(raw_hyde_queries, list):
            hyde_queries = [
                _as_str(value).strip()
                for value in raw_hyde_queries
                if _as_str(value).strip()
            ]
            if hyde_queries:
                normalized["hyde_queries"] = hyde_queries[:8]
        if isinstance(item.get("hyde_aggregation"), str):
            aggregation = _as_str(item.get("hyde_aggregation")).strip()
            if aggregation:
                normalized["hyde_aggregation"] = aggregation
    return normalized


def _runtime_context(runtime: Runtime[Any] | None) -> dict[str, Any]:
    if runtime is None:
        return {}
    context = getattr(runtime, "context", None)
    return context if isinstance(context, dict) else {}


def _resolve_kb_ids(state: dict[str, Any], runtime: Runtime[Any] | None) -> list[str] | None:
    context = _runtime_context(runtime)
    kb_ids_ctx = context.get("kb_ids")
    if isinstance(kb_ids_ctx, list):
        normalized = [str(item).strip() for item in kb_ids_ctx if str(item).strip()]
        if normalized:
            return normalized
    memory_keys = state.get("memory_keys")
    kb_ids = memory_keys.get("kb_ids") if isinstance(memory_keys, dict) else None
    if isinstance(kb_ids, list):
        normalized = [str(item).strip() for item in kb_ids if str(item).strip()]
        if normalized:
            return normalized
    return None


def _dispatch_quality_score(item: dict[str, Any], *, spec: dict[str, Any]) -> float:
    kind = _as_str(item.get("kind")).strip() or "other"
    priority = item.get("priority")
    if not isinstance(priority, int):
        priority = spec.get("priority")
    if not isinstance(priority, int):
        priority = 1 if kind == "main" else 4
    tags = spec.get("coverage_tags")
    if not isinstance(tags, list):
        tags = item.get("coverage_tags")
    if not isinstance(tags, list):
        tags = []
    unique_tags = {
        _as_str(tag).strip().casefold()
        for tag in tags
        if _as_str(tag).strip()
    }
    kind_bonus = {
        "subquery": 0.65,
        "variant": 0.55,
        "main": 0.45,
        "hyde": 0.30,
    }.get(kind, 0.20)
    coverage_bonus = min(len(unique_tags), 4) * 0.1
    # Lower priority value means higher urgency; cap to keep score stable.
    priority_bonus = max(0, 8 - max(1, min(priority, 8))) * 0.12
    return round(kind_bonus + coverage_bonus + priority_bonus, 4)


def _build_subquery_dispatch_plan(
    state: DispatchSubqueriesInput,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> tuple[list[Send] | str, dict[str, Any]]:
    """Build fanout tasks from query_items and return route + diagnostics."""
    strategy = str(state.get("query_strategy") or "direct")
    min_queries = parallel_retrieval_min_queries(state, settings, runtime=runtime)
    max_branches = parallel_retrieval_max_branches(state, settings, runtime=runtime)
    include_main = parallel_retrieval_include_main(state, settings, runtime=runtime)

    raw_query_items = state.get("query_items")
    if not isinstance(raw_query_items, list):
        raw_query_items = []
    normalized_items = [
        item
        for item in (_normalize_query_item(raw_item) for raw_item in raw_query_items)
        if isinstance(item, dict)
    ]

    allowed_kinds_by_strategy: dict[str, set[str]] = {
        "decomposition": {"subquery", "hyde", "main"},
        "multi_query": {"variant", "hyde", "main"},
        "direct": {"main", "hyde"},
    }
    allowed_kinds = allowed_kinds_by_strategy.get(strategy, {"main"})
    candidate_items: list[dict[str, Any]] = []
    for item in normalized_items:
        kind = _as_str(item.get("kind")).strip() or "other"
        if kind not in allowed_kinds:
            continue
        if kind == "main" and not include_main:
            continue
        candidate_items.append(item)
    if not candidate_items and strategy == "decomposition":
        raw_sub_queries = state.get("sub_queries")
        if isinstance(raw_sub_queries, list):
            for index, value in enumerate(raw_sub_queries):
                query = _as_str(value).strip()
                if not query:
                    continue
                candidate_items.append(
                    {
                        "kind": "subquery",
                        "query": query,
                        "index": index,
                        "use_dense": True,
                        "use_bm25": True,
                    }
                )

    if strategy == "direct":
        non_main = [item for item in candidate_items if _as_str(item.get("kind")) != "main"]
        if not non_main:
            return "retrieve", {
                "mode": "single_retrieve",
                "strategy": strategy,
                "reason": "direct_single_query",
                "min_queries": min_queries,
                "max_branches": max_branches,
                "include_main": include_main,
                "branch_count": 0,
                "branch_kinds": {},
            }

    if len(candidate_items) < min_queries:
        return "retrieve", {
            "mode": "single_retrieve",
            "strategy": strategy,
            "reason": "below_min_queries",
            "min_queries": min_queries,
            "max_branches": max_branches,
            "include_main": include_main,
            "branch_count": 0,
            "branch_kinds": {},
        }

    spec_map: dict[str, dict[str, Any]] = {}
    for spec in _resolve_subquery_specs(state):
        query = str(spec.get("query") or "").strip()
        if query:
            spec_map[query.casefold()] = spec

    ranked_candidates: list[dict[str, Any]] = []
    for idx, item in enumerate(candidate_items):
        query = _as_str(item.get("query")).strip()
        if not query:
            continue
        spec = spec_map.get(query.casefold()) or {}
        ranked_candidates.append(
            {
                "item": item,
                "score": _dispatch_quality_score(item, spec=spec),
                "index": idx,
            }
        )
    ranked_candidates.sort(
        key=lambda row: (
            -float(row.get("score") or 0.0),
            int((row.get("item") or {}).get("priority") or 99),
            int(row.get("index") or 0),
        )
    )
    selected_items = [
        row.get("item")
        for row in ranked_candidates[:max_branches]
        if isinstance(row.get("item"), dict)
    ]
    send_tasks: list[Send] = []
    branch_kinds: dict[str, int] = {}
    selected_queries: list[str] = []
    for idx, item in enumerate(selected_items):
        query = _as_str(item.get("query")).strip()
        if not query:
            continue
        kind = _as_str(item.get("kind")).strip() or "other"
        spec = spec_map.get(query.casefold()) or {}
        item_priority = item.get("priority")
        raw_priority = (
            item_priority
            if isinstance(item_priority, int)
            else spec.get("priority")
        )
        if isinstance(raw_priority, int):
            priority = raw_priority
        elif kind == "main":
            priority = 1
        elif kind == "hyde":
            priority = 7
        else:
            priority = idx + 2
        coverage_tags = spec.get("coverage_tags")
        if not isinstance(coverage_tags, list):
            coverage_tags = item.get("coverage_tags")
        if not isinstance(coverage_tags, list):
            coverage_tags = []
        raw_purpose = spec.get("purpose")
        if not isinstance(raw_purpose, str):
            raw_purpose = item.get("purpose")
        purpose = _as_str(raw_purpose).strip()
        raw_subquery_id = item.get("subquery_id")
        if isinstance(raw_subquery_id, str) and raw_subquery_id.strip():
            subquery_id = raw_subquery_id.strip()
        else:
            subquery_index = item.get("index")
            if isinstance(subquery_index, int):
                subquery_id = f"{kind}_{subquery_index + 1}"
            else:
                subquery_id = f"{kind}_{idx + 1}"
        subquery_task = {
            "subquery_id": subquery_id,
            "index": idx,
            "query": query,
            "kind": kind,
            "priority": max(1, min(int(priority), 8)),
            "purpose": purpose,
            "coverage_tags": [
                str(tag).strip()
                for tag in coverage_tags
                if isinstance(tag, str) and str(tag).strip()
            ][:6],
            "query_item": item,
        }
        branch_kinds[kind] = int(branch_kinds.get(kind, 0)) + 1
        selected_queries.append(query)
        send_tasks.append(make_send_task("retrieve_subquery", {"subquery_task": subquery_task}, state))
    if not send_tasks:
        return "retrieve", {
            "mode": "single_retrieve",
            "strategy": strategy,
            "reason": "empty_send_tasks",
            "min_queries": min_queries,
            "max_branches": max_branches,
            "include_main": include_main,
            "branch_count": 0,
            "branch_kinds": {},
        }
    return send_tasks, {
        "mode": "parallel_fanout",
        "strategy": strategy,
        "reason": "fanout",
        "min_queries": min_queries,
        "max_branches": max_branches,
        "include_main": include_main,
        "branch_count": len(send_tasks),
        "branch_kinds": branch_kinds,
        "selected_queries": selected_queries[:8],
        "rank_strategy": "quality_first",
    }

def _resolve_retrieval_timeout_seconds(
    state: dict[str, Any],
    runtime: Runtime[Any] | None = None,
) -> float | None:
    context = _runtime_context(runtime)
    runtime_config = context.get("runtime_config")
    if isinstance(runtime_config, dict):
        raw_timeout = runtime_config.get("retrieval_timeout_seconds")
        if isinstance(raw_timeout, (int, float)) and float(raw_timeout) > 0:
            return float(raw_timeout)
    runtime_state = state.get("runtime_config")
    if isinstance(runtime_state, dict):
        raw_timeout = runtime_state.get("retrieval_timeout_seconds")
        if isinstance(raw_timeout, (int, float)) and float(raw_timeout) > 0:
            return float(raw_timeout)
    return None


def _resolve_retrieval_budget_payload(
    state: dict[str, Any],
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, int]:
    default_top_k = retrieval_top_k(state, settings, runtime=runtime)
    budget = state.get("retrieval_budget")
    if not isinstance(budget, dict):
        budget = {}
    per_query_top_k = int(budget.get("per_query_top_k") or default_top_k)
    global_candidates_limit = int(
        budget.get("global_candidates_limit") or max(default_top_k * 2, per_query_top_k)
    )
    rerank_input_limit = int(
        budget.get("rerank_input_limit")
        or max(default_top_k, per_query_top_k)
    )
    return {
        "per_query_top_k": max(1, per_query_top_k),
        "global_candidates_limit": max(1, global_candidates_limit),
        "rerank_input_limit": max(1, rerank_input_limit),
    }


def _compute_retrieval_diagnostics(
    *,
    state: dict[str, Any],
    final_context: str,
    evidence_count: int,
) -> dict[str, float]:
    query_items = state.get("query_items")
    if isinstance(query_items, list):
        query_count = sum(
            1
            for item in query_items
            if isinstance(item, dict) and _as_str(item.get("query")).strip()
        )
    else:
        query_count = 0
    query_count = max(1, query_count)
    coverage = min(1.0, evidence_count / query_count)

    metrics = state.get("metrics")
    retrieval_metrics = (
        metrics.get("retrieval_layer")
        if isinstance(metrics, dict) and isinstance(metrics.get("retrieval_layer"), dict)
        else {}
    )
    previous_evidence = int(retrieval_metrics.get("evidence_count") or 0)
    if evidence_count <= 0:
        novelty = 0.0
    elif previous_evidence <= 0:
        novelty = 1.0
    else:
        novelty = max(
            0.0,
            min(
                1.0,
                (evidence_count - previous_evidence) / max(evidence_count, previous_evidence),
            ),
        )

    lower_ctx = final_context.lower()
    conflict_markers = (
        final_context.count("但是")
        + final_context.count("然而")
        + lower_ctx.count("however")
        + lower_ctx.count("but ")
    )
    conflict = min(1.0, conflict_markers / max(1, evidence_count * 2))
    return {
        "coverage": round(coverage, 4),
        "novelty": round(novelty, 4),
        "conflict": round(conflict, 4),
    }


async def dispatch_subqueries(
    state: DispatchSubqueriesInput,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> Command[str]:
    start = time.perf_counter()
    goto, diagnostics = _build_subquery_dispatch_plan(state, settings, runtime=runtime)
    stage_summary = {
        **diagnostics,
        "kb_count": len(_resolve_kb_ids(state, runtime) or []),
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "completed_at": now_iso(),
    }
    return Command(
        update={
            "retrieval_plan": {
                "mode": diagnostics.get("mode"),
                "branch_count": diagnostics.get("branch_count"),
                "rank_strategy": diagnostics.get("rank_strategy"),
                "selected_queries": diagnostics.get("selected_queries"),
                "reason": diagnostics.get("reason"),
            },
            **_merge_stage_summary(state, "dispatch_subqueries", stage_summary),
        },
        goto=goto,
    )


async def _invoke_kb_retrieve(
    *,
    state: dict[str, Any],
    query: str,
    settings: Settings,
    kb_tool: BaseTool,
    retrieval_round: int,
    runtime: Runtime[Any] | None = None,
    query_items: list[dict[str, Any]] | None = None,
) -> tuple[str, str | None]:
    kb_ids = _resolve_kb_ids(state, runtime)
    retrieval_budget = _resolve_retrieval_budget_payload(
        state,
        settings,
        runtime=runtime,
    )
    timeout_seconds = _resolve_retrieval_timeout_seconds(state, runtime=runtime)
    try:
        payload = build_retrieval_payload(
            query=query,
            kb_ids=kb_ids or [],
            top_k=retrieval_top_k(state, settings, runtime=runtime),
            retrieval_round=retrieval_round,
            query_items=query_items,
            per_query_top_k=retrieval_budget["per_query_top_k"],
            global_candidates_limit=retrieval_budget["global_candidates_limit"],
            rerank_input_limit=retrieval_budget["rerank_input_limit"],
            timeout_seconds=timeout_seconds,
        )
        context = await kb_tool.ainvoke(payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        return "（未找到相关内容）", "exception"
    return _as_str(context).strip(), None


async def retrieve_subquery_context(
    state: RetrieveSubqueryContextInput,
    *,
    settings: Settings,
    kb_tool: BaseTool,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Run retrieval for a single subquery task (fanout branch)."""
    task = state.get("subquery_task")
    if not isinstance(task, dict):
        return {}

    query_item = _normalize_query_item(task.get("query_item"))
    query = _as_str(task.get("query")).strip()
    if isinstance(query_item, dict):
        query = _as_str(query_item.get("query")).strip() or query
    if not query:
        return {}

    retrieval_round = _current_retrieval_round(state)
    context_text, retrieval_reason = await _invoke_kb_retrieve(
        state=state,
        query=query,
        settings=settings,
        kb_tool=kb_tool,
        retrieval_round=retrieval_round,
        runtime=runtime,
        query_items=[query_item] if isinstance(query_item, dict) else None,
    )

    kind = _as_str(task.get("kind")).strip() or "other"
    if isinstance(query_item, dict):
        kind = _as_str(query_item.get("kind")).strip() or kind
    retrieval_count = _extract_evidence_count(context_text)

    return {
        "subquery_runs": [
            {
                "subquery_id": _as_str(task.get("subquery_id")) or "sq_unknown",
                "index": int(task.get("index") or 0),
                "query": query,
                "retrieval_round": retrieval_round,
                "kind": kind,
                "priority": int(task.get("priority") or 1),
                "purpose": _as_str(task.get("purpose")),
                "coverage_tags": task.get("coverage_tags")
                if isinstance(task.get("coverage_tags"), list)
                else [],
                "query_used": query,
                "context": context_text,
                "used_query_item_bundle": isinstance(query_item, dict),
                "retrieval_count": retrieval_count,
                "success": retrieval_reason is None,
                "reason": retrieval_reason,
            }
        ]
    }


async def merge_subquery_context(
    state: MergeSubqueryContextInput,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Aggregate fanout retrieval outputs into final_context + metrics."""
    start = time.perf_counter()
    active_round = _current_retrieval_round(state)
    raw_runs = state.get("subquery_runs")
    if not isinstance(raw_runs, list):
        raw_runs = []

    runs: list[dict[str, Any]] = []
    for run in raw_runs:
        if not isinstance(run, dict):
            continue
        run_round = run.get("retrieval_round")
        if isinstance(run_round, int) and run_round != active_round:
            continue
        if run_round is None and active_round > 0:
            continue
        runs.append(run)
    runs = sort_by_priority_then_index(runs)

    merged_parts: list[str] = []
    seen_contexts: set[str] = set()
    success_count = 0
    branch_kinds: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    retrieval_count = 0
    for run in runs:
        kind = _as_str(run.get("kind")).strip() or "other"
        branch_kinds[kind] = int(branch_kinds.get(kind, 0)) + 1
        reason = _as_str(run.get("reason")).strip()
        if reason:
            failure_reasons[reason] = int(failure_reasons.get(reason, 0)) + 1
        context = _as_str(run.get("context")).strip()
        if not context:
            continue
        retrieval_count += int(run.get("retrieval_count") or 0)
        key = context.casefold()
        if key in seen_contexts:
            continue
        seen_contexts.add(key)
        merged_parts.append(context)
        if bool(run.get("success")):
            success_count += 1

    final_context = "\n\n".join(merged_parts).strip() if merged_parts else "（未找到相关内容）"
    evidence_count = _extract_evidence_count(final_context)
    retrieval_diagnostics = _compute_retrieval_diagnostics(
        state=state,
        final_context=final_context,
        evidence_count=evidence_count,
    )

    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    metrics = {
        **metrics,
        "retrieval_layer": {
            "evidence_count": evidence_count,
            "retrieval_count": retrieval_count or evidence_count,
            "attempted": True,
            "mode": "parallel_fanout",
            "branch_count": len(runs),
            "branch_success_count": success_count,
            "branch_kinds": branch_kinds,
            "failure_reasons": failure_reasons,
            "kb_count": len(_resolve_kb_ids(state, runtime) or []),
            "diagnostics": retrieval_diagnostics,
        },
    }
    metrics = ensure_json_safe(metrics, settings=settings, label="metrics")

    return {
        "final_context": final_context,
        "retrieval_plan": {
            "mode": "parallel_fanout",
            "branch_count": len(runs),
            "rank_strategy": "quality_first",
            "selected_queries": [
                _as_str(run.get("query")).strip()
                for run in runs
                if _as_str(run.get("query")).strip()
            ][:8],
            "reason": "fanout",
            "diagnostics": retrieval_diagnostics,
        },
        "metrics": metrics,
        "retrieval_diagnostics": retrieval_diagnostics,
        **_merge_stage_summary(
            state,
            "retrieval_layer",
            {
                "retrieval_round": active_round,
                "mode": "parallel_fanout",
                "branch_count": len(runs),
                "branch_success_count": success_count,
                "branch_failure_count": max(len(runs) - success_count, 0),
                "branch_kinds": branch_kinds,
                "evidence_count": evidence_count,
                "retrieval_count": retrieval_count or evidence_count,
                "failure_reasons": failure_reasons,
                "kb_count": len(_resolve_kb_ids(state, runtime) or []),
                "diagnostics": retrieval_diagnostics,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }

def _merge_stage_summary(
    state: dict, key: str, summary: dict[str, Any]
) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    settings = get_settings()
    safe_summary = ensure_json_safe(
        summary, settings=settings, label=f"stage_summaries.{key}"
    )
    merged = {**stage_summaries, key: safe_summary}
    merged = ensure_json_safe(merged, settings=settings, label="stage_summaries")
    return {"stage_summaries": merged}


def _merge_reflection(state: dict, patch: dict[str, Any]) -> dict[str, Any]:
    reflection = state.get("reflection")
    if not isinstance(reflection, dict):
        reflection = {}
    return {"reflection": {**reflection, **patch}}


def _set_final_answer_for_exit(
    state: dict, answer: str, *, reason: str
) -> dict[str, Any]:
    # ForceExit node prefers final_answer; set it explicitly so we don't leak history AIMessage.
    return {
        "final_answer": answer,
        **_merge_reflection(state, {"action": "force_exit", "reason": reason}),
    }
def _resolve_query_text(state: dict) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


async def kb_retrieve_context(
    state: RetrieveContextInput,
    *,
    settings: Settings,
    kb_tool: BaseTool,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Run kb_retrieve once and store the resulting Top-N context into state.final_context."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return _set_final_answer_for_exit(state, "", reason="max_total_rounds")
    query = _resolve_query_text(state)
    retrieval_round = max(loop_counts.get("retrieval_retries", 0), 0)
    query_items = state.get("query_items")
    final_context, retrieval_reason = await _invoke_kb_retrieve(
        state=state,
        query=query,
        settings=settings,
        kb_tool=kb_tool,
        retrieval_round=retrieval_round,
        runtime=runtime,
        query_items=query_items if isinstance(query_items, list) and query_items else None,
    )
    evidence_count = _extract_evidence_count(final_context)
    if retrieval_reason is None and evidence_count <= 0:
        retrieval_reason = "no_evidence"
    retrieval_diagnostics = _compute_retrieval_diagnostics(
        state=state,
        final_context=final_context,
        evidence_count=evidence_count,
    )

    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    metrics = {
        **metrics,
        "retrieval_layer": {
            "evidence_count": evidence_count,
            "retrieval_count": evidence_count,
            "attempted": True,
            "mode": "single_retrieve",
            "kb_count": len(_resolve_kb_ids(state, runtime) or []),
            "diagnostics": retrieval_diagnostics,
        },
    }
    metrics = ensure_json_safe(metrics, settings=settings, label="metrics")

    return {
        "final_context": final_context,
        "retrieval_plan": {
            "mode": "single_retrieve",
            "branch_count": 1,
            "rank_strategy": "quality_first",
            "selected_queries": [query] if query else [],
                "reason": retrieval_reason or "ok",
                "diagnostics": retrieval_diagnostics,
            },
        "metrics": metrics,
        "retrieval_diagnostics": retrieval_diagnostics,
        **_merge_stage_summary(
            state,
            "retrieval_layer",
            {
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "evidence_count": evidence_count,
                "retrieval_count": evidence_count,
                "query_used": query,
                "reason": retrieval_reason,
                "fallback_reason": retrieval_reason,
                "mode": "single_retrieve",
                "kb_count": len(_resolve_kb_ids(state, runtime) or []),
                "diagnostics": retrieval_diagnostics,
                "completed_at": now_iso(),
            },
        ),
    }


async def generate_draft(
    state: dict,
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    """Generate a draft answer using ONLY Top-N final_context; do not append to messages."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)

    # Budget accounting: count each generation as one "round".
    loop_counts = {**loop_counts, "total_rounds": loop_counts["total_rounds"] + 1}

    if _total_rounds_exceeded(loop_counts, settings):
        # Prefer current best draft if any.
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state, _as_str(state.get("draft_answer")), reason="max_total_rounds"
            ),
        }
    if loop_counts["generation_retries"] > int(settings.kb_chat_max_generation_retries):
        return {
            "loop_counts": loop_counts,
            **_set_final_answer_for_exit(
                state,
                _as_str(state.get("draft_answer")),
                reason="max_generation_retries",
            ),
        }

    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    prompts = get_prompt_loader()
    system_prompt = prompts.render_with_few_shot('kb_chat/system')

    user = f"参考内容：\n{final_context}\n\n问题：{question}"

    model = chat_model.bind(max_tokens=1024)
    try:
        msg = await model.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user)]
        )
        draft = extract_answer_text(getattr(msg, "content", "")).strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        draft = ""

    if not draft:
        draft = "根据现有资料无法回答该问题（生成失败）。"

    return {
        "loop_counts": loop_counts,
        "draft_answer": draft,
        # Keep final_answer aligned so ForceExit can always return something sane.
        "final_answer": draft,
        **_merge_stage_summary(
            state,
            "generator",
            {
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }

async def transform_query_for_retry(
    state: TransformQueryInput,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Transform query and bump retrieval_retries (budget-aware)."""
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
            timeout_seconds=0,
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
        normalize_result = await svc.normalize_rewrite(
            new_query,
            llm_enabled=True,
            alias_limit=normalize_alias_max(state, settings, runtime=runtime),
            timeout_seconds=normalize_timeout_seconds(state, settings, runtime=runtime),
        )
        if normalize_result.query.strip():
            new_query = normalize_result.query.strip()
        if isinstance(normalize_result.meta, dict):
            normalized_meta = normalize_result.meta
    except asyncio.CancelledError:
        raise
    except Exception:
        normalized_meta = {}

    hyde_docs: list[str] = []
    hyde_reason: str | None = None
    hyde_should_regenerate = HYDE_REGENERATE_ON_RETRY
    if hyde_should_regenerate:
        try:
            svc = QueryRewriteService(settings=settings)
            hyde_result = await svc.hyde(new_query, enabled=True)
            hyde_docs = [
                value
                for value in hyde_result.queries
                if isinstance(value, str) and value.strip()
            ]
            hyde_reason = hyde_result.reason
        except asyncio.CancelledError:
            raise
        except Exception:
            hyde_docs = []
            hyde_reason = "error"

    # Keep query bundle consistent: after transform, rebuild retrieval inputs.
    aliases = normalized_meta.get("aliases") if isinstance(normalized_meta.get("aliases"), list) else []
    query_items = build_query_items(
        main_query=new_query,
        variants=[str(v) for v in aliases if isinstance(v, str)],
        hyde_docs=hyde_docs or None,
        hyde_note="retry_regenerated" if hyde_docs else None,
    )

    return {
        "loop_counts": loop_counts,
        "normalized_query": new_query,
        "normalized_meta": normalized_meta,
        "coref_query": new_query,
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": hyde_docs,
        "query_items": query_items,
        "decomposition_plan": {
            "strategy": "direct",
            "version": "kb_chat_decomposition_plan_v2",
            "sub_query_specs": [],
            "risk_flags": ["retry_rewrite"],
            "reasoning": _as_str(reason) or "retry",
        },
        **_merge_reflection(
            state,
            {
                "action": "transform_query",
                "reason": _as_str(reason) or "retry",
                "hint": _as_str(hint),
            },
        ),
        **_merge_stage_summary(
            state,
            "transform_query",
            {
                "rewritten": new_query != current,
                "normalized_after_retry": True,
                "normalization_source": str(normalized_meta.get("source") or ""),
                "hyde_regenerated": bool(hyde_docs),
                "hyde_docs_count": len(hyde_docs),
                "hyde_reason": hyde_reason,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


def route_after_doc_grader(state: DocGateRoutingDecisionInput, settings: Settings) -> str:
    """Route after DocGrader: answer_subgraph vs transform_query vs force_exit."""
    routing = resolve_routing_decision(state, "doc_gate")
    next_node = _as_str(routing.get("next_node")).strip()
    if next_node in {"answer_subgraph", "transform_query", "force_exit"}:
        return next_node
    loop_counts = _get_loop_counts(state)
    if loop_counts["retrieval_retries"] >= int(
        getattr(settings, "kb_chat_max_retrieval_retries", 2)
    ):
        return "force_exit"
    return "transform_query"


def route_after_answer_review(state: AnswerRoutingDecisionInput, settings: Settings) -> str:
    """Route after AnswerReview: confidence_calibrate vs transform_query vs force_exit."""
    routing = resolve_routing_decision(state, "answer_subgraph")
    next_node = _as_str(routing.get("next_node")).strip()
    if next_node in {"confidence_calibrate", "transform_query", "force_exit"}:
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


def confidence_calibrate(state: ConfidenceCalibrateInput) -> dict[str, Any]:
    """Calibrate final confidence from gate/review/citation/retrieval/CoVe signals."""
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    doc_gate_route = resolve_routing_decision(state, "doc_gate")
    reflection = state.get("reflection")
    gate_signal = 0.0
    if isinstance(doc_gate_route, dict):
        gate_signal = float(doc_gate_route.get("score") or 0.0)
    if gate_signal <= 0.0 and isinstance(reflection, dict):
        gate_signal = float(reflection.get("confidence") or 0.0)
    gate_signal = max(0.0, min(1.0, gate_signal))
    gate_reason = _as_str(doc_gate_route.get("reason")) if isinstance(doc_gate_route, dict) else ""
    review_conf = (
        float(reflection.get("review_confidence") or 0.0)
        if isinstance(reflection, dict)
        else 0.0
    )
    cove_state = state.get("cove_state")
    cove_passed = (
        bool(cove_state.get("passed"))
        if isinstance(cove_state, dict) and cove_state.get("passed") is not None
        else True
    )
    claim_check_passed = (
        bool(cove_state.get("claim_check_passed"))
        if isinstance(cove_state, dict) and cove_state.get("claim_check_passed") is not None
        else True
    )
    loop_counts = state.get("loop_counts")
    retry_counts = loop_counts if isinstance(loop_counts, dict) else {}
    total_retries = max(
        0,
        int(retry_counts.get("retrieval_retries") or 0)
        + int(retry_counts.get("generation_retries") or 0),
    )
    review_signal = max(0.0, min(1.0, review_conf * max(0.0, 1.0 - (0.2 * total_retries))))

    citation_coverage = float(
        (cove_state.get("claim_coverage") if isinstance(cove_state, dict) else 0.0)
        or 0.0
    )
    citation_coverage = max(0.0, min(1.0, citation_coverage))

    retrieval_diagnostics = state.get("retrieval_diagnostics")
    retrieval_metrics = retrieval_diagnostics if isinstance(retrieval_diagnostics, dict) else {}
    top1_score = retrieval_metrics.get("top1_score")
    top2_score = retrieval_metrics.get("top2_score")
    if isinstance(top1_score, (int, float)) and isinstance(top2_score, (int, float)):
        retrieval_signal = max(0.0, min(1.0, float(top1_score) - float(top2_score)))
    else:
        coverage = max(0.0, min(1.0, float(retrieval_metrics.get("coverage") or 0.0)))
        novelty = max(0.0, min(1.0, float(retrieval_metrics.get("novelty") or 0.0)))
        conflict = max(0.0, min(1.0, float(retrieval_metrics.get("conflict") or 0.0)))
        retrieval_signal = max(
            0.0,
            min(1.0, (coverage * 0.45) + (novelty * 0.30) + ((1.0 - conflict) * 0.25)),
        )

    if isinstance(cove_state, dict) and bool(cove_state.get("enabled")) and bool(cove_state.get("triggered")):
        raw_cove_signal = cove_state.get("supported_ratio")
        if raw_cove_signal is None:
            raw_cove_signal = 1.0 if cove_passed else 0.0
        cove_signal = max(0.0, min(1.0, float(raw_cove_signal or 0.0)))
    else:
        cove_signal = 1.0

    if not claim_check_passed:
        citation_coverage *= 0.8
    if gate_reason == "retry":
        gate_signal *= 0.85

    weights = {
        "gate_signal": Decimal("0.30"),
        "review_signal": Decimal("0.20"),
        "citation_coverage": Decimal("0.25"),
        "retrieval_signal": Decimal("0.15"),
        "cove_signal": Decimal("0.10"),
    }
    weighted_sum = (
        Decimal(str(max(0.0, min(1.0, gate_signal)))) * weights["gate_signal"]
        + Decimal(str(review_signal)) * weights["review_signal"]
        + Decimal(str(citation_coverage)) * weights["citation_coverage"]
        + Decimal(str(retrieval_signal)) * weights["retrieval_signal"]
        + Decimal(str(cove_signal)) * weights["cove_signal"]
    )
    confidence_score = float(
        max(Decimal("0.0"), min(Decimal("1.0"), weighted_sum)).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )
    )
    if confidence_score >= 0.8:
        confidence_level = "high"
    elif confidence_score >= 0.5:
        confidence_level = "medium"
    else:
        confidence_level = "low"

    signal_breakdown = {
        "gate_signal": round(max(0.0, min(1.0, gate_signal)), 4),
        "review_signal": round(review_signal, 4),
        "citation_coverage": round(citation_coverage, 4),
        "retrieval_signal": round(retrieval_signal, 4),
        "cove_signal": round(cove_signal, 4),
        "total_retries": total_retries,
    }
    stage_summaries = {
        **stage_summaries,
        "confidence_calibrate": {
            "confidence_score": confidence_score,
            "confidence_level": confidence_level,
            "gate_confidence": round(gate_signal, 4),
            "review_confidence": round(review_conf, 4),
            "citation_coverage": round(citation_coverage, 4),
            "retrieval_signal": round(retrieval_signal, 4),
            "cove_signal": round(cove_signal, 4),
            "signals": signal_breakdown,
            "reason": (
                "weighted_multi_signal"
                if claim_check_passed and cove_passed
                else "penalized_after_validation"
            ),
            "cove_passed": cove_passed,
            "claim_check_passed": claim_check_passed,
            "completed_at": now_iso(),
        },
    }
    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    metrics = {
        **metrics,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
    }
    return {
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "stage_summaries": stage_summaries,
        "metrics": metrics,
    }


def finalize_answer(state: FinalizeAnswerInput) -> dict[str, Any]:
    """Emit final answer as an AIMessage (stream-visible)."""
    final_answer = _as_str(
        state.get("draft_answer") or state.get("final_answer")
    ).strip()
    if not final_answer:
        final_answer = "根据现有资料无法回答该问题（未生成答案）。"
    return {
        "final_answer": final_answer,
        "messages": [AIMessage(content=final_answer)],
    }

