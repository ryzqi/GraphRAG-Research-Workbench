"""KB Chat agentic ReflectionLayer 节点（相关性 / 答案审查）。

设计目标：
- 保持最小实现且适合生产使用，并提供兜底
- 仅向状态写入近似 JSON 的可序列化值
- 感知预算，并将路由绑定到 loop_counts 的轮次 / 重试预算
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import re
import time
import uuid
from typing import Any

from langchain.messages import HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from app.core.settings import Settings, get_settings
from app.integrations.chat_model_factory import create_chat_model
from app.prompts import get_prompt_loader
from app.services.kb_answer_paragraphs import (
    normalize_answer_text_variants,
    recalculate_paragraph_citation_ids,
    render_answer_paragraphs,
)
from app.services.streaming import extract_answer_text
from app.services.kb_evidence import (
    resolve_structured_evidence,
)
from app.services.query_rewrite_service import (
    QueryRewriteService,
    coerce_structured_result_payload,
)
from app.services.query_rewrite_text import (
    _extract_multi_target_entities_for_guardrail,
    _extract_required_dimension_keywords_for_guardrail,
)
from app.agents.kb_chat_agentic_state import (
    AnswerRoutingDecisionInput,
    DispatchSubqueriesInput,
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
from .preprocess import run_query_plan_scheme_b, score_query_item_quality
from .schemas import AnswerParagraph, AnswerRenderMeta, DraftAnswerDecision
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

_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
StateView = Mapping[str, object]
_INLINE_CITATION_RE = re.compile(r"\[([^\[\]\n]{1,128})\]|【([^【】\n]{1,128})】")
_CITATION_ONLY_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
}
_LATIN_TERM_RE = re.compile(r"[（(]([A-Za-z][A-Za-z0-9\-/ ]{1,64})[)）]")
_RESPONSIBILITY_LABEL_RE = re.compile(
    r"(?:核心任务|职责|作用)\s*[：:]\s*([^（(。\n；;，,]+)"
)
_RESPONSIBILITY_STAGE_RE = re.compile(
    r"负责([^，。,；;\n（(]{1,20})(?:[（(]([^()（）\n]{1,32})[)）])?"
)


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _as_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _get_loop_counts(state: StateView) -> dict[str, int]:
    raw = state.get("loop_counts")
    if not isinstance(raw, dict):
        return {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0}
    return {
        "total_rounds": int(raw.get("total_rounds") or 0),
        "retrieval_retries": int(raw.get("retrieval_retries") or 0),
        "generation_retries": int(raw.get("generation_retries") or 0),
    }


def _current_retrieval_round(state: StateView) -> int:
    loop_counts = _get_loop_counts(state)
    return max(int(loop_counts.get("retrieval_retries") or 0), 0)


def _total_rounds_exceeded(loop_counts: dict[str, int], settings: Settings) -> bool:
    return loop_counts.get("total_rounds", 0) >= int(settings.kb_chat_max_total_rounds)


def _extract_evidence_count(final_context: str) -> int:
    if not final_context:
        return 0
    return sum(1 for _ in _EVIDENCE_LINE_RE.finditer(final_context))


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


def _merge_stage_summary(
    state: StateView, key: str, summary: dict[str, Any]
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


def _merge_reflection(state: StateView, patch: dict[str, Any]) -> dict[str, Any]:
    reflection = state.get("reflection")
    if not isinstance(reflection, dict):
        reflection = {}
    return {"reflection": {**reflection, **patch}}


def _set_final_answer_for_exit(
    state: StateView, answer: str, *, reason: str
) -> dict[str, Any]:
    # ForceExit 节点优先使用 final_answer；这里显式设置，避免泄露历史 AIMessage。
    return {
        "final_answer": answer,
        **_merge_reflection(state, {"action": "force_exit", "reason": reason}),
    }


def _resolve_query_text(state: StateView) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("resolved_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


def _extract_question_entities(question: str) -> list[str]:
    return _extract_multi_target_entities_for_guardrail(question)


def _extract_required_dimensions(question: str) -> list[str]:
    return [
        label
        for label, _ in _extract_required_dimension_keywords_for_guardrail(question)
    ]


def _extract_required_term_map(
    entities: list[str],
    *,
    final_context: str,
    required_dimensions: list[str] | None = None,
) -> dict[str, list[str]]:
    if not entities or not final_context:
        return {}

    required_dimensions = required_dimensions or []
    blocks: list[str] = []
    current_block: list[str] = []
    for raw_line in _as_str(final_context).splitlines():
        line = _as_str(raw_line)
        if _EVIDENCE_LINE_RE.match(line):
            if current_block:
                block = "\n".join(current_block).strip()
                if block:
                    blocks.append(block)
            current_block = [line]
            continue
        if current_block:
            current_block.append(line)
    if current_block:
        block = "\n".join(current_block).strip()
        if block:
            blocks.append(block)
    if not blocks:
        blocks = [_as_str(final_context).strip()]

    def _normalize_required_term(term: object) -> str:
        normalized = _as_str(term)
        normalized = normalized.replace("**", "").replace("__", "").strip()
        normalized = re.split(r"[（(]", normalized, maxsplit=1)[0]
        normalized = re.split(r"[。；;，,\n]", normalized, maxsplit=1)[0]
        normalized = normalized.strip(" -*_`：:、")
        return normalized

    def _append_term(terms: list[str], term: object) -> None:
        normalized = _normalize_required_term(term)
        if not normalized or normalized in terms:
            return
        terms.append(normalized)

    def _extract_block_terms(block: str) -> list[str]:
        terms: list[str] = []
        lines = [line.strip() for line in _as_str(block).splitlines() if line.strip()]
        if "职责" in required_dimensions:
            for line in lines:
                if "核心任务" in line or "职责" in line or "作用" in line:
                    for match in _RESPONSIBILITY_LABEL_RE.finditer(line):
                        _append_term(terms, match.group(1))
                if "负责" in line:
                    for match in _RESPONSIBILITY_STAGE_RE.finditer(line):
                        parenthetical = _normalize_required_term(match.group(2))
                        if parenthetical:
                            _append_term(terms, parenthetical)
                            continue
                        stage_or_label = _normalize_required_term(match.group(1))
                        if stage_or_label and (
                            stage_or_label.endswith("阶段") or len(stage_or_label) <= 6
                        ):
                            _append_term(terms, stage_or_label)
        if "技术架构" in required_dimensions:
            for line in lines:
                if not any(
                    keyword in line
                    for keyword in ("技术架构", "架构", "采用", "结构", "编码器")
                ):
                    continue
                for match in _LATIN_TERM_RE.finditer(line):
                    _append_term(terms, match.group(1))
        return terms

    term_map: dict[str, list[str]] = {}
    for entity in entities:
        entity_key = re.sub(r"\s+", "", entity).casefold()
        terms: list[str] = []
        relevant_blocks = [
            block
            for block in blocks
            if entity_key and entity_key in re.sub(r"\s+", "", block).casefold()
        ]
        if not relevant_blocks and len(blocks) == len(entities):
            entity_index = entities.index(entity)
            if 0 <= entity_index < len(blocks):
                relevant_blocks = [blocks[entity_index]]
        for block in relevant_blocks:
            for term in _extract_block_terms(block):
                _append_term(terms, term)
        if terms:
            term_map[entity] = terms[:4]
    return term_map


def _build_answer_coverage_hint(question: str, final_context: str = "") -> str:
    entities = _extract_question_entities(question)
    if len(entities) < 2:
        return ""

    dimensions = _extract_required_dimensions(question)
    dimension_text = " / ".join(dimensions) if dimensions else "问题要求的关键信息"
    required_terms = _extract_required_term_map(
        entities,
        final_context=final_context,
        required_dimensions=dimensions,
    )
    lines = ["覆盖清单："]
    for entity in entities:
        line = f"- {entity}: {dimension_text}"
        terms = required_terms.get(entity)
        if terms:
            line += f"；必须保留原始名词：{' / '.join(terms)}"
        lines.append(line)
    lines.extend(
        [
            "额外约束：",
            "- 必须按上面的实体 × 维度逐项覆盖；若某个维度无证据，只能说明该维度缺证，不得把整实体写成“资料不足”。",
            "- 只要参考内容中已经出现某实体或其原始术语，就不得声称“参考内容未提供该实体信息”。",
            "- 对技术架构、职责标签或阶段名类问题，必须显式保留参考内容中的原始名词或标签。",
        ]
    )
    return "\n".join(lines)


def _compact_answer_coverage_text(text: str) -> str:
    normalized = normalize_answer_text_variants(_as_str(text))
    return re.sub(r"[\s\-‐‑‒–—―_]+", "", normalized).casefold()


def _detect_draft_coverage_gap(
    *,
    question: str,
    draft: str,
    final_context: str,
) -> dict[str, object] | None:
    entities = _extract_question_entities(question)
    if len(entities) < 2:
        return None

    compact_answer = _compact_answer_coverage_text(draft)
    missing_entities = [
        entity
        for entity in entities
        if _compact_answer_coverage_text(entity) not in compact_answer
    ]
    if missing_entities:
        return {
            "reason": "incomplete",
            "missing_entities": missing_entities,
            "required_dimensions": _extract_required_dimensions(question),
            "coverage_guardrail": "multi_entity_entities",
        }

    required_dimensions = _extract_required_dimensions(question)
    requires_original_terms = any(
        dimension in required_dimensions for dimension in ("职责", "技术架构")
    ) or any(
        keyword in _as_str(question)
        for keyword in ("模型名称", "组件名称", "术语", "名词清单")
    )
    if not requires_original_terms:
        return None

    required_term_map = _extract_required_term_map(
        entities,
        final_context=final_context,
        required_dimensions=required_dimensions,
    )
    if not required_term_map:
        return None

    missing_terms: dict[str, list[str]] = {}
    for entity in entities:
        compact_entity = _compact_answer_coverage_text(entity)
        if compact_entity not in compact_answer:
            continue
        terms = required_term_map.get(entity) or []
        missing_for_entity = [
            term
            for term in terms
            if _compact_answer_coverage_text(term) not in compact_answer
        ]
        if missing_for_entity:
            missing_terms[entity] = missing_for_entity
    if not missing_terms:
        return None
    return {
        "reason": "incomplete",
        "missing_terms": missing_terms,
        "required_dimensions": required_dimensions,
        "coverage_guardrail": "required_original_terms",
    }


def _format_draft_coverage_gap(gap: dict[str, object] | None) -> str:
    if not isinstance(gap, dict) or not gap:
        return ""
    lines = ["当前草稿存在以下覆盖缺口："]
    missing_entities = gap.get("missing_entities")
    if isinstance(missing_entities, list) and missing_entities:
        lines.append(
            f"- 缺少实体覆盖：{' / '.join(_as_str(entity) for entity in missing_entities)}"
        )
    missing_terms = gap.get("missing_terms")
    if isinstance(missing_terms, dict):
        for entity, terms in missing_terms.items():
            if not isinstance(terms, list) or not terms:
                continue
            lines.append(
                f"- {_as_str(entity)} 缺少原始名词：{' / '.join(_as_str(term) for term in terms)}"
            )
    return "\n".join(lines)


async def _attempt_local_plain_text_draft_repair(
    *,
    chat_model: BaseChatModel,
    system_prompt: str,
    question: str,
    final_context: str,
    coverage_block: str,
    draft: str,
    coverage_gap: dict[str, object],
) -> tuple[list[dict[str, Any]], dict[str, Any], str] | None:
    gap_block = _format_draft_coverage_gap(coverage_gap)
    repair_user = (
        "请修复下面这份回答草稿，仅输出最终答案正文。\n"
        "要求：\n"
        "1) 必须按实体 × 维度逐项覆盖问题要求的信息；\n"
        "2) 若参考内容已出现某实体或术语，不得把该实体整体写成“资料不足”或“未提供”；\n"
        "3) 对技术架构、职责标签或阶段名类问题，必须显式保留参考内容中的原始名词或标签；\n"
        "4) 仅使用参考内容中的事实，并在每段结尾保留有效 [Sx] 聚合引用；\n"
        "5) 不要输出 JSON、代码块或额外解释。\n\n"
        f"{gap_block}\n\n"
        f"{coverage_block}"
        f"问题：{question}\n\n"
        f"参考内容：\n{final_context}\n\n"
        f"原回答：\n{draft}"
    )
    try:
        repair_model = chat_model.bind(max_tokens=1024)
        repair_msg = await repair_model.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=repair_user)]
        )
        candidate = extract_answer_text(getattr(repair_msg, "content", "")).strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        return None
    if not candidate:
        return None

    projected = _project_plain_text_answer_to_paragraphs(
        candidate,
        allowed_citation_ids=_extract_allowed_citation_ids(final_context),
    )
    if not projected:
        return None

    repaired_payloads = [paragraph.model_dump() for paragraph in projected]
    repaired_render_meta = _build_answer_render_meta(projected)
    repaired_draft = render_answer_paragraphs(repaired_payloads).strip()
    if (
        _detect_draft_coverage_gap(
            question=question,
            draft=repaired_draft,
            final_context=final_context,
        )
        is not None
    ):
        return None
    return repaired_payloads, repaired_render_meta, repaired_draft


def _coerce_draft_answer_decision(
    payload: object,
) -> tuple[DraftAnswerDecision | None, str | None]:
    if payload is None:
        return None, "empty_structured_response"
    try:
        decision = (
            payload
            if isinstance(payload, DraftAnswerDecision)
            else DraftAnswerDecision.model_validate(payload)
        )
    except Exception:
        return None, "structured_parse_failed"
    if not decision.paragraphs:
        return decision, "empty_structured_paragraphs"
    return decision, None


def _merge_draft_structured_reason(
    *,
    payload_reason: str | None,
    decision_reason: str | None,
) -> str | None:
    if decision_reason is None:
        return payload_reason
    if (
        payload_reason
        in {"invalid_schema", "structured_parse_failed", "multiple_structured_outputs"}
        and decision_reason == "empty_structured_response"
    ):
        return payload_reason
    return decision_reason or payload_reason


def _should_retry_draft_structured(reason: str | None) -> bool:
    return reason in {
        "structured_invoke_failed",
        "empty_structured_response",
        "invalid_schema",
        "structured_parse_failed",
        "multiple_structured_outputs",
    }


def _can_project_plain_text_after_structured_failure(reason: str | None) -> bool:
    return reason in {
        "empty_structured_paragraphs",
        "empty_structured_response",
        "invalid_schema",
        "structured_parse_failed",
        "multiple_structured_outputs",
    }


def _build_draft_retry_chat_model(*, settings: Settings) -> BaseChatModel | Any | None:
    try:
        retry_model = create_chat_model(
            settings=settings,
            use_previous_response_id=False,
        )
    except Exception:
        return None
    return retry_model


async def _invoke_draft_structured(
    *,
    chat_model: BaseChatModel,
    messages: list[SystemMessage | HumanMessage],
) -> tuple[list[dict[str, Any]], dict[str, Any], str, str | None]:
    structured_reason: str | None = None
    paragraph_payloads: list[dict[str, Any]] = []
    render_meta = _build_answer_render_meta([])
    draft = ""

    try:
        structured_model = chat_model.with_structured_output(
            DraftAnswerDecision,
            method="function_calling",
            include_raw=True,
        )
        result = await structured_model.ainvoke(messages)
        payload, payload_reason = coerce_structured_result_payload(
            result=result,
            schema=DraftAnswerDecision,
        )
        decision, decision_reason = _coerce_draft_answer_decision(payload)
        structured_reason = _merge_draft_structured_reason(
            payload_reason=payload_reason,
            decision_reason=decision_reason,
        )
        if decision is not None:
            paragraphs = _normalize_answer_paragraphs(
                [
                    AnswerParagraph.model_validate(paragraph)
                    for paragraph in decision.paragraphs
                ]
            )
            paragraph_payloads = [paragraph.model_dump() for paragraph in paragraphs]
            render_meta = _build_answer_render_meta(paragraphs)
            draft = render_answer_paragraphs(paragraph_payloads).strip()
    except asyncio.CancelledError:
        raise
    except Exception:
        structured_reason = "structured_invoke_failed"

    return paragraph_payloads, render_meta, draft, structured_reason


def _normalize_answer_paragraphs(
    paragraphs: list[AnswerParagraph],
) -> list[AnswerParagraph]:
    normalized: list[AnswerParagraph] = []
    seen_ids: set[str] = set()
    for index, paragraph in enumerate(paragraphs, start=1):
        paragraph_id = paragraph.paragraph_id.strip() or f"p{index}"
        if paragraph_id in seen_ids:
            paragraph_id = f"p{index}"
        seen_ids.add(paragraph_id)
        normalized.append(
            recalculate_paragraph_citation_ids(
                paragraph.model_copy(update={"paragraph_id": paragraph_id})
            )
        )
    return normalized


def _build_answer_render_meta(
    paragraphs: list[AnswerParagraph],
) -> dict[str, Any]:
    citation_ids: list[str] = []
    claim_count = 0
    for paragraph in paragraphs:
        claim_count += len(paragraph.claims)
        citation_ids.extend(paragraph.citation_ids)
    return AnswerRenderMeta(
        paragraph_count=len(paragraphs),
        claim_count=claim_count,
        citation_count=len(dict.fromkeys(citation_ids)),
        citation_mode="paragraph_aggregate",
    ).model_dump()


def _extract_allowed_citation_ids(final_context: str) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for match in _EVIDENCE_LINE_RE.finditer(final_context or ""):
        citation_id = _as_str(match.group(1)).strip()
        if citation_id:
            allowed.setdefault(citation_id.casefold(), citation_id)
    return allowed


def _extract_inline_citation_ids(text: str) -> list[str]:
    normalized = normalize_answer_text_variants(_as_str(text))
    return [
        _as_str(match.group(1) or match.group(2)).strip()
        for match in _INLINE_CITATION_RE.finditer(normalized)
        if _as_str(match.group(1) or match.group(2)).strip()
    ]


def _strip_inline_citations(text: str) -> str:
    stripped = _INLINE_CITATION_RE.sub(
        "", normalize_answer_text_variants(_as_str(text))
    )
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def _project_plain_text_answer_to_paragraphs(
    answer: str,
    *,
    allowed_citation_ids: dict[str, str],
) -> list[AnswerParagraph]:
    cleaned_answer = normalize_answer_text_variants(_as_str(answer)).strip()
    if not cleaned_answer:
        return []

    raw_blocks = [
        block.strip() for block in re.split(r"\n\s*\n", cleaned_answer) if block.strip()
    ]
    if not raw_blocks:
        raw_blocks = [cleaned_answer]
    merged_blocks: list[str] = []
    index = 0
    while index < len(raw_blocks):
        block = raw_blocks[index]
        current_citations = _extract_inline_citation_ids(block)
        if (
            not current_citations
            and index + 1 < len(raw_blocks)
            and _extract_inline_citation_ids(raw_blocks[index + 1])
        ):
            merged_blocks.append(f"{block}\n\n{raw_blocks[index + 1]}")
            index += 2
            continue
        merged_blocks.append(block)
        index += 1

    paragraphs: list[AnswerParagraph] = []
    for index, block in enumerate(merged_blocks, start=1):
        citation_ids: list[str] = []
        for citation_id in _extract_inline_citation_ids(block):
            canonical = allowed_citation_ids.get(citation_id.casefold())
            if canonical and canonical not in citation_ids:
                citation_ids.append(canonical)
        text = _strip_inline_citations(block)
        if not text and not citation_ids:
            continue
        paragraphs.append(
            AnswerParagraph(
                paragraph_id=f"p{index}",
                text=text,
                citation_ids=citation_ids,
                claims=[],
                review_status="passed",
            )
        )
    return paragraphs


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


async def generate_draft(
    state: Mapping[str, object],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    """仅基于 Top-N final_context 生成草稿答案；不要追加到 messages。"""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)

    # 预算统计：每次生成都记作一轮。
    loop_counts = {**loop_counts, "total_rounds": loop_counts["total_rounds"] + 1}

    if _total_rounds_exceeded(loop_counts, settings):
        # 若存在当前最优草稿，则优先使用。
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
    coverage_hint = _build_answer_coverage_hint(question, final_context)
    coverage_block = f"{coverage_hint}\n\n" if coverage_hint else ""
    prompts = get_prompt_loader()
    system_prompt = prompts.render_with_few_shot("kb_chat/system")

    user = (
        "请基于参考内容回答问题，并按结构化段落返回。\n"
        "要求：\n"
        "1) paragraphs 按自然段组织，每段 text 只写正文，不要内嵌 [Sx] 标签；\n"
        "2) citation_ids 只填写该段主旨所依赖的可见引用标签，如 S1、S2；\n"
        "3) 默认采用段末聚合引用，不要求逐句引用，但段内关键结论必须能被该段 citation_ids 支撑；\n"
        "4) claims 仅保留该段关键断言；supporting_citation_ids 只填有效 Sx 标签；\n"
        "5) 若参考内容不足以形成可回答段落，返回空 paragraphs，不要编造。\n"
        "6) 不要输出 Markdown 代码块、解释性前言或 schema 外字段。\n\n"
        f"{coverage_block}"
        f"参考内容：\n{final_context}\n\n"
        f"问题：{question}"
    )

    structured_reason: str | None = None
    paragraph_payloads: list[dict[str, Any]] = []
    render_meta = _build_answer_render_meta([])
    draft = ""
    draft_messages: list[SystemMessage | HumanMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user),
    ]

    (
        paragraph_payloads,
        render_meta,
        draft,
        structured_reason,
    ) = await _invoke_draft_structured(
        chat_model=chat_model,
        messages=draft_messages,
    )

    if not draft and _should_retry_draft_structured(structured_reason):
        retry_chat_model = _build_draft_retry_chat_model(settings=settings)
        if retry_chat_model is not None:
            (
                retry_paragraph_payloads,
                retry_render_meta,
                retry_draft,
                retry_reason,
            ) = await _invoke_draft_structured(
                chat_model=retry_chat_model,
                messages=draft_messages,
            )
            if retry_draft:
                paragraph_payloads = retry_paragraph_payloads
                render_meta = retry_render_meta
                draft = retry_draft
                structured_reason = retry_reason
            else:
                structured_reason = retry_reason or structured_reason

    if not draft:
        if (
            _can_project_plain_text_after_structured_failure(structured_reason)
            and final_context
            and question
        ):
            plain_user = (
                "请基于参考内容直接回答问题，仅输出最终答案正文。\n"
                "要求：\n"
                "1) 仅使用参考内容中的事实；\n"
                "2) 默认采用段落级聚合引用：每段结尾统一附带有效 [Sx]；\n"
                "3) 若问题同时要求多个必答子项，必须逐一覆盖；\n"
                "4) 若参考内容已出现某实体或术语，不得把该实体整体写成“资料不足”。\n"
                "5) 不要输出 JSON、代码块或额外解释。\n\n"
                f"{coverage_block}"
                f"参考内容：\n{final_context}\n\n"
                f"问题：{question}"
            )
            try:
                plain_model = chat_model.bind(max_tokens=1024)
                plain_msg = await plain_model.ainvoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=plain_user),
                    ]
                )
                candidate = extract_answer_text(
                    getattr(plain_msg, "content", "")
                ).strip()
                projected = _project_plain_text_answer_to_paragraphs(
                    candidate,
                    allowed_citation_ids=_extract_allowed_citation_ids(final_context),
                )
                if projected:
                    paragraph_payloads = [
                        paragraph.model_dump() for paragraph in projected
                    ]
                    render_meta = _build_answer_render_meta(projected)
                    draft = render_answer_paragraphs(paragraph_payloads).strip()
                    structured_reason = (
                        f"{structured_reason}_recovered_by_plain_text_projection"
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        if not draft:
            if structured_reason == "empty_structured_paragraphs":
                draft = "根据现有资料无法回答该问题。"
            else:
                draft = "根据现有资料无法回答该问题（生成失败）。"
    elif final_context and question:
        coverage_gap = _detect_draft_coverage_gap(
            question=question,
            draft=draft,
            final_context=final_context,
        )
        if coverage_gap is not None:
            repaired = await _attempt_local_plain_text_draft_repair(
                chat_model=chat_model,
                system_prompt=system_prompt,
                question=question,
                final_context=final_context,
                coverage_block=coverage_block,
                draft=draft,
                coverage_gap=coverage_gap,
            )
            if repaired is not None:
                paragraph_payloads, render_meta, draft = repaired

    generator_summary = {
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "paragraph_count": int(render_meta.get("paragraph_count") or 0),
        "claim_count": int(render_meta.get("claim_count") or 0),
        "citation_count": int(render_meta.get("citation_count") or 0),
        "citation_mode": render_meta.get("citation_mode") or "paragraph_aggregate",
        "fallback_reason": structured_reason,
        "completed_at": now_iso(),
    }
    summary_updates = _merge_stage_summary(state, "generator", generator_summary)
    draft_generate_state = {
        **state,
        **summary_updates,
    }
    summary_updates.update(
        _merge_stage_summary(
            draft_generate_state,
            "draft_generate",
            {
                "paragraph_count": int(render_meta.get("paragraph_count") or 0),
                "claim_count": int(render_meta.get("claim_count") or 0),
                "citation_count": int(render_meta.get("citation_count") or 0),
                "citation_mode": render_meta.get("citation_mode")
                or "paragraph_aggregate",
                "completed_at": now_iso(),
            },
        )
    )

    return {
        "loop_counts": loop_counts,
        "answer_paragraphs": paragraph_payloads,
        "answer_render_meta": render_meta,
        "draft_answer": draft,
        # 保持 final_answer 同步，确保 ForceExit 始终能返回合理内容。
        "final_answer": draft,
        **summary_updates,
    }


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
