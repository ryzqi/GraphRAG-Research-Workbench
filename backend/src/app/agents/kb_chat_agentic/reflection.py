"""KB Chat agentic ReflectionLayer nodes (relevance / answer-review).

These nodes are designed to be:
- Minimal & production-safe (fallbacks)
- Serializable-friendly (only write JSON-ish values to state)
- Budget-aware (bind routing to loop_counts rounds/retries budgets)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command, Send
from pydantic import BaseModel, ValidationError

from app.core.settings import Settings, get_settings
from app.prompts import get_prompt_loader
from app.services.evidence_guardrails import (
    extract_citation_labels,
    normalize_citation_label,
)
from app.services.query_rewrite_service import (
    HYDE_REGENERATE_ON_RETRY,
    QueryRewriteService,
    build_query_items,
)

from .budget import now_iso
from .json_safety import ensure_json_safe
from .runtime_config import (
    doc_gate_fallback_open_when_evidence_ok,
    doc_gate_llm_confidence_floor,
    doc_gate_rule_threshold,
    hyde_enabled,
    normalize_alias_max,
    normalize_llm_enabled,
    normalize_timeout_seconds,
    parallel_retrieval_enabled,
    parallel_retrieval_include_main,
    parallel_retrieval_max_branches,
    parallel_retrieval_min_queries,
    query_rewrite_enabled,
    retrieval_top_k,
)
from .schemas import AnswerReviewDecision, DocGraderDecision

_EVIDENCE_LINE_RE = re.compile(r"^\[([^\[\]\n]{1,128})\]\s+", re.MULTILINE)
_CITATION_ONLY_FAILURE_REASONS = {
    "missing_citations",
    "invalid_citations",
    "citation_mismatch",
    # Backward compatibility for old checkpoints.
    "missing_or_invalid_citations",
}
_DOC_GATE_RISK_LEVELS = {"low", "medium", "high"}
_DOC_GATE_RETRY_ADVICES = {"none", "retry", "clarify"}


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


def _total_rounds_exceeded(loop_counts: dict[str, int], settings: Settings) -> bool:
    return loop_counts.get("total_rounds", 0) >= int(settings.kb_chat_max_total_rounds)


def _normalize_citation_label(value: str) -> str:
    return normalize_citation_label(value)


def _extract_evidence_labels(final_context: str) -> dict[str, str]:
    if not final_context:
        return {}
    labels: dict[str, str] = {}
    for match in _EVIDENCE_LINE_RE.finditer(final_context):
        label = _normalize_citation_label(match.group(1))
        if not label:
            continue
        labels.setdefault(label.casefold(), label)
    return labels


def _extract_evidence_count(final_context: str) -> int:
    if not final_context:
        return 0
    return sum(1 for _ in _EVIDENCE_LINE_RE.finditer(final_context))


def _tokenize_query_terms(query: str) -> set[str]:
    if not query:
        return set()
    lowered = query.lower()
    terms = re.findall(r"[\w\u4e00-\u9fff]{2,}", lowered)
    return {term for term in terms if len(term) >= 2}


def _estimate_evidence_score(question: str, final_context: str) -> float:
    labels = _extract_evidence_labels(final_context)
    label_count = len(labels)
    if label_count <= 0:
        return 0.0
    query_terms = _tokenize_query_terms(question)
    lower_ctx = final_context.lower()
    overlap = sum(1 for term in query_terms if term and term in lower_ctx)
    overlap_ratio = (
        min(1.0, overlap / max(1, min(len(query_terms), 6)))
        if query_terms
        else 0.0
    )
    label_score = min(1.0, label_count / 4)
    score = 0.6 * label_score + 0.4 * overlap_ratio
    return round(max(0.0, min(1.0, score)), 4)


def _default_missing_constraints(reason: str) -> list[str]:
    if reason == "insufficient":
        return ["关键约束"]
    if reason == "too_broad":
        return ["限定条件"]
    if reason == "needs_clarification":
        return ["对象/范围/时间/口径"]
    if reason in {"no_evidence", "not_relevant"}:
        return ["相关证据"]
    return []


def _normalize_doc_gate_reason(reason: object, *, passed: bool) -> str:
    value = _as_str(reason).strip()
    allowed = {
        "passed",
        "no_evidence",
        "not_relevant",
        "insufficient",
        "too_broad",
        "needs_clarification",
        "fallback_open",
        "fallback_closed",
    }
    if value in allowed:
        return value
    return "passed" if passed else "insufficient"


def _normalize_risk_level(value: object, *, passed: bool) -> str:
    risk = _as_str(value).strip().lower()
    if risk in _DOC_GATE_RISK_LEVELS:
        return risk
    return "low" if passed else "medium"


def _normalize_retry_advice(value: object, *, passed: bool) -> str:
    advice = _as_str(value).strip().lower()
    if advice in _DOC_GATE_RETRY_ADVICES:
        return advice
    return "none" if passed else "retry"


def _missing_constraints_hint(missing_constraints: list[str]) -> str:
    cleaned = [_as_str(item).strip() for item in missing_constraints if _as_str(item).strip()]
    return "、".join(cleaned[:3])


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
    state: dict,
    settings: Settings,
) -> tuple[list[Send] | str, dict[str, Any]]:
    """Build fanout tasks from query_items and return route + diagnostics."""
    strategy = str(state.get("query_strategy") or "direct")
    min_queries = parallel_retrieval_min_queries(state, settings)
    max_branches = parallel_retrieval_max_branches(state, settings)
    include_main = parallel_retrieval_include_main(state, settings)
    if not parallel_retrieval_enabled(state, settings):
        return "retrieve", {
            "mode": "single_retrieve",
            "strategy": strategy,
            "reason": "parallel_disabled",
            "min_queries": min_queries,
            "max_branches": max_branches,
            "include_main": include_main,
            "branch_count": 0,
            "branch_kinds": {},
        }

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
        send_tasks.append(
            Send(
                "retrieve_subquery",
                {
                    "subquery_task": subquery_task,
                    "memory_keys": state.get("memory_keys"),
                    "loop_counts": state.get("loop_counts"),
                    "runtime_config": state.get("runtime_config"),
                },
            )
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


def route_after_subquery_dispatch(
    state: dict,
    settings: Settings,
) -> list[Send] | str:
    route, _ = _build_subquery_dispatch_plan(state, settings)
    return route


async def dispatch_subqueries(
    state: dict,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> Command[str]:
    start = time.perf_counter()
    goto, diagnostics = _build_subquery_dispatch_plan(state, settings)
    stage_summary = {
        **diagnostics,
        "kb_count": len(_resolve_kb_ids(state, runtime) or []),
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "completed_at": now_iso(),
    }
    return Command(
        update={
            "subquery_runs": [],
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


async def retrieve_subquery_context(
    state: dict,
    *,
    settings: Settings,
    kb_tool: BaseTool,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Run retrieval for a single subquery task (fanout branch)."""
    task = state.get("subquery_task")
    if not isinstance(task, dict):
        return {"subquery_runs": []}

    query_item = _normalize_query_item(task.get("query_item"))
    query = _as_str(task.get("query")).strip()
    if isinstance(query_item, dict):
        query = _as_str(query_item.get("query")).strip() or query
    if not query:
        return {"subquery_runs": []}

    loop_counts = _get_loop_counts(state)
    retrieval_round = max(loop_counts.get("retrieval_retries", 0), 0)
    kb_ids = _resolve_kb_ids(state, runtime)

    retrieval_reason: str | None = None
    try:
        payload: dict[str, Any] = {
            "query": query,
            "kb_ids": kb_ids,
            "top_k": retrieval_top_k(state, settings),
            "retrieval_round": retrieval_round,
        }
        if isinstance(query_item, dict):
            payload["query_items"] = [query_item]
        context = await kb_tool.ainvoke(payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        retrieval_reason = "exception"
        context = "（未找到相关内容）"

    kind = _as_str(task.get("kind")).strip() or "other"
    if isinstance(query_item, dict):
        kind = _as_str(query_item.get("kind")).strip() or kind
    context_text = _as_str(context).strip()
    retrieval_count = _extract_evidence_count(context_text)

    return {
        "subquery_runs": [
            {
                "subquery_id": _as_str(task.get("subquery_id")) or "sq_unknown",
                "index": int(task.get("index") or 0),
                "query": query,
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
    state: dict,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Aggregate fanout retrieval outputs into final_context + metrics."""
    start = time.perf_counter()
    raw_runs = state.get("subquery_runs")
    if not isinstance(raw_runs, list):
        raw_runs = []

    runs = [run for run in raw_runs if isinstance(run, dict)]
    runs = sorted(
        runs,
        key=lambda item: (
            int(item.get("priority") or 99),
            int(item.get("index") or 0),
        ),
    )

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
        },
        "metrics": metrics,
        "subquery_runs": [],
        **_merge_stage_summary(
            state,
            "retrieval_layer",
            {
                "mode": "parallel_fanout",
                "branch_count": len(runs),
                "branch_success_count": success_count,
                "branch_failure_count": max(len(runs) - success_count, 0),
                "branch_kinds": branch_kinds,
                "evidence_count": evidence_count,
                "retrieval_count": retrieval_count or evidence_count,
                "failure_reasons": failure_reasons,
                "kb_count": len(_resolve_kb_ids(state, runtime) or []),
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


def _partition_citations(
    answer: str, *, allowed_labels: dict[str, str]
) -> tuple[list[str], set[str], set[str]]:
    if not answer or not allowed_labels:
        return [], set(), set()
    all_citations = extract_citation_labels(answer)
    valid_found: set[str] = set()
    invalid_found: set[str] = set()
    for label in all_citations:
        key = label.casefold()
        if key in allowed_labels:
            valid_found.add(allowed_labels[key])
        else:
            invalid_found.add(label)
    return all_citations, valid_found, invalid_found


def _render_prompt_or_default(prompt_key: str, default: str) -> str:
    prompts = get_prompt_loader()
    try:
        return prompts.render_with_few_shot(prompt_key)
    except KeyError:
        return default


_StructuredT = TypeVar("_StructuredT", bound=BaseModel)


def _classify_structured_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    if name == "StructuredOutputValidationError":
        return "invalid_schema"
    if name == "MultipleStructuredOutputsError":
        return "multiple_structured_outputs"
    return "error"


async def _judge_structured(
    *,
    chat_model: ChatOpenAI,
    schema: type[_StructuredT],
    system: str,
    user: str,
) -> tuple[_StructuredT | None, str | None]:
    agent = create_agent(
        model=chat_model,
        tools=[],
        system_prompt=system,
        response_format=schema,
    )
    request = {"messages": [{"role": "user", "content": user}]}
    try:
        result = await agent.ainvoke(request)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, _classify_structured_error(exc)
    if not isinstance(result, dict):
        return None, "empty_structured_response"
    structured_payload = result.get("structured_response")
    if structured_payload is None:
        return None, "empty_structured_response"
    if isinstance(structured_payload, schema):
        return structured_payload, None
    try:
        payload = schema.model_validate(structured_payload)
    except ValidationError:
        return None, "invalid_schema"
    return payload, None


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


def _force_exit_requested(state: dict) -> bool:
    reflection = state.get("reflection")
    return isinstance(reflection, dict) and reflection.get("action") == "force_exit"


def _doc_gate_state(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("doc_gate_state")
    return raw if isinstance(raw, dict) else {}


def _merge_doc_gate_state(
    state: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    merged = {**_doc_gate_state(state), **patch}
    return {"doc_gate_state": merged}


def _resolve_query_text(state: dict) -> str:
    return _as_str(
        state.get("normalized_query")
        or state.get("coref_query")
        or state.get("rewrite_input_query")
        or state.get("user_input")
    ).strip()


async def kb_retrieve_context(
    state: dict,
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
    kb_ids = _resolve_kb_ids(state, runtime)

    retrieval_round = max(loop_counts.get("retrieval_retries", 0), 0)
    retrieval_reason: str | None = None
    try:
        payload: dict[str, Any] = {
            "query": query,
            "kb_ids": kb_ids,
            "top_k": retrieval_top_k(state, settings),
            "retrieval_round": retrieval_round,
        }
        query_items = state.get("query_items")
        if isinstance(query_items, list) and query_items:
            # Pass fanout query bundle to kb_retrieve so RetrievalService.retrieve_layer() can do cross-query fusion.
            payload["query_items"] = query_items
        context = await kb_tool.ainvoke(payload)
    except asyncio.CancelledError:
        raise
    except Exception:
        retrieval_reason = "exception"
        context = "（未找到相关内容）"

    final_context = _as_str(context).strip()
    evidence_count = _extract_evidence_count(final_context)
    if retrieval_reason is None and evidence_count <= 0:
        retrieval_reason = "no_evidence"

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
            "kb_count": len(kb_ids or []),
        },
    }
    metrics = ensure_json_safe(metrics, settings=settings, label="metrics")

    updates: dict[str, Any] = {
        "final_context": final_context,
        "retrieval_plan": {
            "mode": "single_retrieve",
            "branch_count": 1,
            "rank_strategy": "quality_first",
            "selected_queries": [query] if query else [],
            "reason": retrieval_reason or "ok",
        },
        "metrics": metrics,
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
                "kb_count": len(kb_ids or []),
                "completed_at": now_iso(),
            },
        ),
    }
    return updates


async def doc_gate_precheck(
    state: dict,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """Fast rule gate before LLM grading to reduce unnecessary retries/cost."""
    del runtime
    start = time.perf_counter()
    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    evidence_labels = _extract_evidence_labels(final_context)
    evidence_count = len(evidence_labels)
    evidence_score = _estimate_evidence_score(question, final_context)
    threshold = doc_gate_rule_threshold(state, settings)

    passed = False
    reason = "insufficient"
    missing_constraints: list[str] = []
    confidence = 0.0
    risk_level = "medium"
    retry_advice = "retry"
    decision_source = "rule"
    llm_required = True

    if evidence_count <= 0 or "未找到相关内容" in final_context:
        passed = False
        reason = "no_evidence"
        missing_constraints = ["相关证据"]
        confidence = 1.0
        risk_level = "high"
        retry_advice = "retry"
        llm_required = False
    elif evidence_score >= min(1.0, threshold + 0.2) and evidence_count >= 2:
        passed = True
        reason = "passed"
        missing_constraints = []
        confidence = max(0.65, evidence_score)
        risk_level = "low"
        retry_advice = "none"
        llm_required = False
    elif evidence_count >= 2 and evidence_score < max(0.12, threshold * 0.5):
        passed = False
        reason = "not_relevant"
        missing_constraints = ["相关证据"]
        confidence = max(0.55, 1.0 - evidence_score)
        risk_level = "high"
        retry_advice = "retry"
        llm_required = False
    else:
        decision_source = "llm"
        confidence = min(0.6, max(0.2, evidence_score))
        risk_level = "medium" if evidence_score >= threshold else "high"
        retry_advice = "retry"

    patch = {
        "passed": passed,
        "reason": reason,
        "missing_constraints": missing_constraints,
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence_score": round(max(0.0, min(1.0, evidence_score)), 4),
        "risk_level": risk_level,
        "retry_advice": retry_advice,
        "decision_source": decision_source,
        "fallback_used": False,
        "fallback_reason": None,
        "llm_required": llm_required,
    }
    return {
        **_merge_doc_gate_state(state, patch),
        **_merge_stage_summary(
            state,
            "doc_gate_precheck",
            {
                **patch,
                "evidence_count": evidence_count,
                "threshold": threshold,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def doc_grader_llm(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
    runtime: Runtime[Any] | None = None,
) -> dict[str, Any]:
    """LLM grading for boundary samples after rule precheck."""
    del runtime
    start = time.perf_counter()
    gate_state = _doc_gate_state(state)
    if gate_state.get("llm_required") is False:
        return {
            **_merge_stage_summary(
                state,
                "doc_grader_llm",
                {
                    "skipped": True,
                    "reason": "rule_decided",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "completed_at": now_iso(),
                },
            )
        }

    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    threshold = doc_gate_rule_threshold(state, settings)
    confidence_floor = doc_gate_llm_confidence_floor(state, settings)
    passed = bool(gate_state.get("passed"))
    reason = _normalize_doc_gate_reason(gate_state.get("reason"), passed=passed)
    missing_constraints = [
        _as_str(item).strip()
        for item in (gate_state.get("missing_constraints") or [])
        if _as_str(item).strip()
    ][:3]
    confidence = float(gate_state.get("confidence") or 0.0)
    evidence_score = float(
        gate_state.get("evidence_score") or _estimate_evidence_score(question, final_context)
    )
    risk_level = _normalize_risk_level(gate_state.get("risk_level"), passed=passed)
    retry_advice = _normalize_retry_advice(gate_state.get("retry_advice"), passed=passed)
    fallback_used = False
    fallback_reason: str | None = None

    system_prompt = _render_prompt_or_default(
        "kb_chat/doc_grader",
        (
            "You are a strict retrieval relevance grader. "
            "Determine whether the retrieved snippets are directly relevant to the question "
            "and sufficient to support the answer."
            ' Output JSON only: {"passed": true/false, "reason": "..."}'
        ),
    )
    judge: DocGraderDecision | None = None
    judge, fallback_reason = await _judge_structured(
        chat_model=chat_model,
        schema=DocGraderDecision,
        system=system_prompt,
        user=f"问题：{question}\n\n检索片段：\n{final_context[:4000]}",
    )
    if isinstance(judge, DocGraderDecision):
        passed = bool(judge.passed)
        reason = _normalize_doc_gate_reason(judge.reason, passed=passed)
        missing_constraints = [
            _as_str(item).strip()
            for item in (judge.missing_constraints or [])
            if _as_str(item).strip()
        ][:3]
        raw_confidence = max(0.0, min(1.0, float(judge.confidence)))
        confidence = raw_confidence
        evidence_score = max(
            evidence_score,
            max(0.0, min(1.0, float(judge.evidence_score))),
        )
        if passed and raw_confidence <= 0.0:
            confidence = max(confidence, evidence_score, 0.6)
        risk_level = _normalize_risk_level(judge.risk_level, passed=passed)
        retry_advice = _normalize_retry_advice(judge.retry_advice, passed=passed)
    else:
        fallback_used = True
        policy = settings.kb_chat_grader_fail_policy
        allow_open = bool(policy == "open")
        if (
            not allow_open
            and doc_gate_fallback_open_when_evidence_ok(state, settings)
            and evidence_score >= threshold
        ):
            allow_open = True
        passed = allow_open
        reason = "fallback_open" if passed else "fallback_closed"
        if fallback_reason is None:
            fallback_reason = "invalid_schema"
        if passed:
            retry_advice = "none"
            risk_level = "medium"
            missing_constraints = []
        else:
            retry_advice = "retry"
            risk_level = "high"
            missing_constraints = _default_missing_constraints(reason)
        confidence = max(confidence, 0.35)

    if passed and confidence < confidence_floor:
        passed = False
        reason = "insufficient"
        retry_advice = "retry"
        risk_level = "medium"
        if not missing_constraints:
            missing_constraints = ["关键约束"]

    if not passed and not missing_constraints:
        missing_constraints = _default_missing_constraints(reason)
    if passed:
        missing_constraints = []

    patch = {
        "passed": passed,
        "reason": reason,
        "missing_constraints": missing_constraints[:3],
        "confidence": round(max(0.0, min(1.0, confidence)), 4),
        "evidence_score": round(max(0.0, min(1.0, evidence_score)), 4),
        "risk_level": _normalize_risk_level(risk_level, passed=passed),
        "retry_advice": _normalize_retry_advice(retry_advice, passed=passed),
        "decision_source": "llm",
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "llm_required": False,
    }
    return {
        **_merge_doc_gate_state(state, patch),
        **_merge_stage_summary(
            state,
            "doc_grader_llm",
            {
                **patch,
                "confidence_floor": confidence_floor,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def doc_gate_route(
    state: dict,
    *,
    settings: Settings,
    runtime: Runtime[Any] | None = None,
) -> Command[str]:
    """Finalize doc gate decision and route with Command."""
    del runtime
    start = time.perf_counter()
    gate_state = _doc_gate_state(state)
    passed = bool(gate_state.get("passed"))
    reason = _normalize_doc_gate_reason(gate_state.get("reason"), passed=passed)
    missing_constraints = [
        _as_str(item).strip()
        for item in (gate_state.get("missing_constraints") or [])
        if _as_str(item).strip()
    ][:3]
    if not passed and not missing_constraints:
        missing_constraints = _default_missing_constraints(reason)
    hint = _missing_constraints_hint(missing_constraints)
    confidence = round(max(0.0, min(1.0, float(gate_state.get("confidence") or 0.0))), 4)
    evidence_score = round(
        max(0.0, min(1.0, float(gate_state.get("evidence_score") or 0.0))),
        4,
    )
    risk_level = _normalize_risk_level(gate_state.get("risk_level"), passed=passed)
    retry_advice = _normalize_retry_advice(gate_state.get("retry_advice"), passed=passed)
    decision_source = _as_str(gate_state.get("decision_source")).strip() or "rule"
    fallback_used = bool(gate_state.get("fallback_used"))
    fallback_reason = (
        _as_str(gate_state.get("fallback_reason")).strip() or None
    )

    if _force_exit_requested(state):
        goto = "force_exit"
    elif passed:
        goto = "generate"
    else:
        loop_counts = _get_loop_counts(state)
        if retry_advice == "none":
            goto = "force_exit"
        elif loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
            goto = "force_exit"
        elif retry_advice == "clarify" and loop_counts["retrieval_retries"] >= 1:
            goto = "force_exit"
        else:
            goto = "transform_query"

    action = "none" if passed and goto == "generate" else "transform_query"
    if goto == "force_exit":
        action = "force_exit"
    updates: dict[str, Any] = {
        **_merge_doc_gate_state(
            state,
            {
                "passed": passed,
                "reason": reason,
                "missing_constraints": missing_constraints,
                "confidence": confidence,
                "evidence_score": evidence_score,
                "risk_level": risk_level,
                "retry_advice": retry_advice,
                "decision_source": decision_source,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
            },
        ),
        **_merge_reflection(
            state,
            {
                "relevance_passed": passed,
                "action": action,
                "reason": reason,
                "hint": hint,
                "confidence": confidence,
                "evidence_score": evidence_score,
                "risk_level": risk_level,
                "retry_advice": retry_advice,
                "decision_source": decision_source,
            },
        ),
        **_merge_stage_summary(
            state,
            "doc_grader",
            {
                "passed": passed,
                "reason": reason,
                "missing_constraints": missing_constraints,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "confidence": confidence,
                "evidence_score": evidence_score,
                "risk_level": risk_level,
                "retry_advice": retry_advice,
                "decision_source": decision_source,
                "goto": goto,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }

    writer = None
    try:
        writer = get_stream_writer()
    except Exception:
        writer = None
    if callable(writer):
        writer(
            {
                "event_type": "doc_gate_decision",
                "passed": passed,
                "reason": reason,
                "goto": goto,
                "confidence": confidence,
                "evidence_score": evidence_score,
                "risk_level": risk_level,
                "decision_source": decision_source,
                "retry_advice": retry_advice,
                "fallback_reason": fallback_reason,
                "ts": now_iso(),
            }
        )

    return Command(update=updates, goto=goto)


async def doc_grader(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Backward-compatible wrapper: run precheck + llm + route and return updates."""
    precheck_updates = await doc_gate_precheck(state, settings=settings)
    state_after_precheck = {**state, **precheck_updates}
    llm_updates = await doc_grader_llm(
        state_after_precheck, settings=settings, chat_model=chat_model
    )
    state_after_llm = {**state_after_precheck, **llm_updates}
    route_result = await doc_gate_route(state_after_llm, settings=settings)
    route_updates = route_result.update if isinstance(route_result.update, dict) else {}
    return {**precheck_updates, **llm_updates, **route_updates}


async def generate_draft(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
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
        draft = _as_str(getattr(msg, "content", "")).strip()
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


async def answer_review(
    state: dict,
    *,
    settings: Settings,
    chat_model: ChatOpenAI,
) -> dict[str, Any]:
    """Review draft answer in one pass: factual support + answerability + relevance."""
    start = time.perf_counter()
    loop_counts = _get_loop_counts(state)
    question = _resolve_query_text(state)
    final_context = _as_str(state.get("final_context")).strip()
    draft = _as_str(state.get("draft_answer")).strip()

    passed = False
    reason = "empty"
    missing_citations: list[str] = []
    unsupported_claims: list[str] = []
    fallback_used = False
    fallback_reason: str | None = None
    evidence_labels = _extract_evidence_labels(final_context)
    all_citations, valid_citations, invalid_citations = _partition_citations(
        draft, allowed_labels=evidence_labels
    )
    if not draft:
        reason = "empty"
    elif not evidence_labels:
        reason = "no_evidence"
    elif not all_citations:
        reason = "missing_citations"
    elif invalid_citations:
        reason = "invalid_citations"
    else:
        system_prompt = _render_prompt_or_default(
            "kb_chat/answer_review",
            (
                "你是严格的知识库回答审查器。"
                "请同时判断回答是否被参考内容支持且引用有效、并且是否直接回答问题。"
                '仅输出 JSON：{"passed": true/false, "reason": "..."}。'
            ),
        )
        judge: AnswerReviewDecision | None = None
        judge, fallback_reason = await _judge_structured(
            chat_model=chat_model,
            schema=AnswerReviewDecision,
            system=system_prompt,
            user=(
                f"问题：{question}\n\n参考内容：\n{final_context[:4000]}"
                f"\n\n回答：\n{draft[:2000]}"
            ),
        )
        if judge is None:
            fallback_used = True
        if isinstance(judge, AnswerReviewDecision):
            passed = bool(judge.passed)
            reason = judge.reason
            missing_citations = [
                _as_str(item).strip()
                for item in (judge.missing_citations or [])
                if _as_str(item).strip()
            ][:3]
            unsupported_claims = [
                _as_str(item).strip()
                for item in (judge.unsupported_claims or [])
                if _as_str(item).strip()
            ][:3]
        else:
            policy = settings.kb_chat_grader_fail_policy
            passed = policy == "open"
            reason = fallback_reason or (
                "fallback_open" if passed else "fallback_closed"
            )
            if fallback_reason is None:
                fallback_reason = "invalid_schema"

    loop_counts_updates = loop_counts
    action = "none" if passed else "transform_query"
    best_answer_updates: dict[str, Any] = {}
    best_answer_meta: dict[str, Any] | None = None
    if passed:
        if draft:
            best_answer_meta = {
                "from_node": "answer_review",
                "reason": reason,
                "retrieval_round": max(loop_counts.get("retrieval_retries", 0), 0),
                "total_rounds": loop_counts.get("total_rounds", 0),
                "completed_at": now_iso(),
            }
            best_answer_updates = {
                "best_answer": draft,
                "best_answer_meta": best_answer_meta,
            }

    return {
        "loop_counts": loop_counts_updates,
        **best_answer_updates,
        **_merge_reflection(
            state,
            {
                "review_passed": passed,
                "action": action,
                "reason": reason,
            },
        ),
        **_merge_stage_summary(
            state,
            "answer_review",
            {
                "passed": passed,
                "reason": reason,
                "best_answer": draft if passed and draft else None,
                "best_answer_meta": best_answer_meta,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "citation_count": len(all_citations),
                "valid_citation_count": len(valid_citations),
                "invalid_citations": sorted(invalid_citations),
                "missing_citations": missing_citations,
                "unsupported_claims": unsupported_claims,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "completed_at": now_iso(),
            },
        ),
    }


async def transform_query_for_retry(
    state: dict, *, settings: Settings
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
            enabled=query_rewrite_enabled(state, settings),
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
            llm_enabled=normalize_llm_enabled(state, settings),
            alias_limit=normalize_alias_max(state, settings),
            timeout_seconds=normalize_timeout_seconds(state, settings),
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
    hyde_should_regenerate = HYDE_REGENERATE_ON_RETRY and hyde_enabled(state, settings)
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
        "subquery_runs": [],
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


def route_after_doc_grader(state: dict, settings: Settings) -> str:
    """Route after DocGrader: generate vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    reflection = state.get("reflection")
    passed = (
        reflection.get("relevance_passed") if isinstance(reflection, dict) else None
    )
    if passed is True:
        return "generate"
    loop_counts = _get_loop_counts(state)
    if loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
        return "force_exit"
    return "transform_query"


def route_after_answer_review(state: dict, settings: Settings) -> str:
    """Route after AnswerReview: finalize vs transform_query vs force_exit."""
    if _force_exit_requested(state):
        return "force_exit"
    loop_counts = _get_loop_counts(state)
    if _total_rounds_exceeded(loop_counts, settings):
        return "force_exit"

    reflection = state.get("reflection")
    passed = reflection.get("review_passed") if isinstance(reflection, dict) else None
    if passed is True:
        return "finalize"

    reason = _as_str(reflection.get("reason")) if isinstance(reflection, dict) else ""
    if reason in _CITATION_ONLY_FAILURE_REASONS:
        if loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
            return "force_exit"
        return "transform_query"

    if loop_counts["retrieval_retries"] >= int(settings.kb_chat_max_retrieval_retries):
        return "force_exit"
    return "transform_query"


def finalize_answer(state: dict) -> dict[str, Any]:
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
