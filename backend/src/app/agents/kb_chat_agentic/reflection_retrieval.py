"""KB Chat agentic reflection 检索辅助。"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import time
import uuid
from typing import Any

from langchain.tools import BaseTool
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from app.agents.kb_chat_agentic_state import (
    DispatchSubqueriesInput,
    MergeSubqueryContextInput,
    RetrieveContextInput,
    RetrieveSubqueryContextInput,
)
from app.core.settings import Settings
from app.services.kb_evidence import resolve_structured_evidence

from .budget import now_iso
from .dispatch_fuse import (
    build_retrieval_payload,
    make_send_task,
    sort_by_priority_then_index,
)
from .json_safety import ensure_json_safe
from .preprocess import score_query_item_quality
from .reflection_shared import (
    StateView,
    _as_str,
    _current_retrieval_round,
    _extract_evidence_count,
    _get_loop_counts,
    _merge_stage_summary,
    _resolve_query_text,
    _set_final_answer_for_exit,
    _total_rounds_exceeded,
)
from .runtime_config import (
    parallel_retrieval_include_main,
    parallel_retrieval_max_branches,
    parallel_retrieval_min_queries,
    retrieval_top_k,
)
from ..tools.kb_retrieve import (
    push_kb_invocation_request_id,
    reset_kb_invocation_request_id,
)
def _pop_kb_invocation_meta(
    kb_tool: BaseTool,
    *,
    request_id: str,
) -> dict[str, Any] | None:
    store = getattr(kb_tool, "_kb_invocation_meta_by_request_id", None)
    if not isinstance(store, dict):
        return None
    meta = store.pop(request_id, None)
    return meta if isinstance(meta, dict) else None


def _resolve_subquery_specs(state: StateView) -> list[dict[str, Any]]:
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
    quality_score = item.get("quality_score")
    if isinstance(quality_score, (int, float)) and not isinstance(quality_score, bool):
        normalized["quality_score"] = round(float(quality_score), 4)
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


def _resolve_kb_ids(
    state: StateView, runtime: Runtime[Any] | None
) -> list[str] | None:
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


def _dispatch_quality_score(
    item: dict[str, Any],
    *,
    strategy: str,
    spec: dict[str, Any],
) -> float:
    merged_item = {**spec, **item}
    return score_query_item_quality(
        merged_item,
        strategy=strategy,
    )


def _build_subquery_dispatch_plan(
    state: DispatchSubqueriesInput,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> tuple[list[Send] | str, dict[str, Any]]:
    """根据 query_items 构建扇出任务，并返回路由与诊断信息。"""
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
        "decomposition": {"subquery", "variant", "hyde", "main"},
        "paraphrase": {"paraphrase", "hyde", "main"},
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
        non_main = [
            item for item in candidate_items if _as_str(item.get("kind")) != "main"
        ]
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
                "score": _dispatch_quality_score(item, strategy=strategy, spec=spec),
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
    selected_items: list[dict[str, Any]] = []
    for row in ranked_candidates[:max_branches]:
        row_item = row.get("item")
        if isinstance(row_item, dict):
            selected_items.append(row_item)
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
            item_priority if isinstance(item_priority, int) else spec.get("priority")
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
        send_tasks.append(
            make_send_task("retrieve_subquery", {"subquery_task": subquery_task}, state)
        )
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


def _resolve_retrieval_budget_payload(
    state: StateView,
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
        budget.get("rerank_input_limit") or max(default_top_k, per_query_top_k)
    )
    return {
        "per_query_top_k": max(1, per_query_top_k),
        "global_candidates_limit": max(1, global_candidates_limit),
        "rerank_input_limit": max(1, rerank_input_limit),
    }


def _compute_retrieval_diagnostics(
    *,
    state: StateView,
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
    retrieval_layer = metrics.get("retrieval_layer") if isinstance(metrics, dict) else None
    retrieval_metrics = retrieval_layer if isinstance(retrieval_layer, dict) else {}
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
                (evidence_count - previous_evidence)
                / max(evidence_count, previous_evidence),
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
    state: StateView,
    query: str,
    settings: Settings,
    kb_tool: BaseTool,
    retrieval_round: int,
    runtime: Runtime[Any] | None = None,
    query_items: Sequence[Mapping[str, object]] | None = None,
) -> tuple[str, str | None, dict[str, Any]]:
    kb_ids = _resolve_kb_ids(state, runtime)
    retrieval_budget = _resolve_retrieval_budget_payload(
        state,
        settings,
        runtime=runtime,
    )
    request_id = uuid.uuid4().hex
    request_id_token = push_kb_invocation_request_id(request_id)
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
        )
        context = await kb_tool.ainvoke(payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        return "（未找到相关内容）", "exception", {}
    finally:
        reset_kb_invocation_request_id(request_id_token)
    meta = _pop_kb_invocation_meta(kb_tool, request_id=request_id) or {}
    return _as_str(context).strip(), None, meta


async def retrieve_subquery_context(
    state: RetrieveSubqueryContextInput,
    *,
    settings: Settings,
    kb_tool: BaseTool,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """执行单个子查询任务的检索（扇出分支）。"""
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
    context_text, retrieval_reason, retrieval_meta = await _invoke_kb_retrieve(
        state=state,
        query=query,
        settings=settings,
        kb_tool=kb_tool,
        retrieval_round=retrieval_round,
        runtime=runtime,
        query_items=[query_item] if isinstance(query_item, dict) else None,
    )
    meta_dict = retrieval_meta if isinstance(retrieval_meta, dict) else {}
    evidence_items, citation_catalog, canonical_context = resolve_structured_evidence(
        meta_dict.get("evidence_items"),
        citation_catalog=meta_dict.get("citation_catalog"),
    )
    if evidence_items:
        context_text = canonical_context

    kind = _as_str(task.get("kind")).strip() or "other"
    if isinstance(query_item, dict):
        kind = _as_str(query_item.get("kind")).strip() or kind
    retrieval_count = (
        len(evidence_items) if evidence_items else _extract_evidence_count(context_text)
    )

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
                "evidence_items": evidence_items,
                "citation_catalog": citation_catalog,
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
    """将扇出检索结果汇总为 final_context 与 metrics。"""
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
        runs.append(dict(run))
    runs = sort_by_priority_then_index(runs)

    merged_parts: list[str] = []
    merged_evidence_items: list[dict[str, Any]] = []
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
        branch_items, _, _ = resolve_structured_evidence(
            run.get("evidence_items"),
            citation_catalog=run.get("citation_catalog"),
        )
        retrieval_count += int(run.get("retrieval_count") or 0)
        if branch_items:
            merged_evidence_items.extend(branch_items)
        elif context:
            key = context.casefold()
            if key in seen_contexts:
                continue
            seen_contexts.add(key)
            merged_parts.append(context)
        if bool(run.get("success")):
            success_count += 1

    evidence_items, citation_catalog, canonical_context = resolve_structured_evidence(
        merged_evidence_items,
        reindex=True,
    )
    if evidence_items:
        final_context = canonical_context
    else:
        final_context = (
            "\n\n".join(merged_parts).strip() if merged_parts else "（未找到相关内容）"
        )
    evidence_count = (
        len(evidence_items)
        if evidence_items
        else _extract_evidence_count(final_context)
    )
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
        "evidence_items": evidence_items,
        "citation_catalog": citation_catalog,
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



async def kb_retrieve_context(
    state: RetrieveContextInput,
    *,
    settings: Settings,
    kb_tool: BaseTool,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """执行一次 kb_retrieve，并将得到的 Top-N 上下文写入 state.final_context。"""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return _set_final_answer_for_exit(state, "", reason="max_total_rounds")
    query = _resolve_query_text(state)
    retrieval_round = max(loop_counts.get("retrieval_retries", 0), 0)
    query_items = state.get("query_items")
    final_context, retrieval_reason, retrieval_meta = await _invoke_kb_retrieve(
        state=state,
        query=query,
        settings=settings,
        kb_tool=kb_tool,
        retrieval_round=retrieval_round,
        runtime=runtime,
        query_items=query_items
        if isinstance(query_items, list) and query_items
        else None,
    )
    meta_dict = retrieval_meta if isinstance(retrieval_meta, dict) else {}
    evidence_items, citation_catalog, canonical_context = resolve_structured_evidence(
        meta_dict.get("evidence_items"),
        citation_catalog=meta_dict.get("citation_catalog"),
    )
    if evidence_items:
        final_context = canonical_context
    evidence_count = (
        len(evidence_items)
        if evidence_items
        else _extract_evidence_count(final_context)
    )
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
        "evidence_items": evidence_items,
        "citation_catalog": citation_catalog,
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


