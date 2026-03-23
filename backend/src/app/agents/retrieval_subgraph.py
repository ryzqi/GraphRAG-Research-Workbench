"""Retrieval subgraph for KB Chat flowchart Stage 4."""

from __future__ import annotations

import asyncio
from functools import partial
import re
import time
from typing import Any, TypedDict

from langchain.messages import HumanMessage, SystemMessage
from langchain.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy
from pydantic import ValidationError

from app.agents.kb_chat_agentic.budget import now_iso
from app.agents.kb_chat_agentic.schemas import ContextCompressDecision
from app.agents.kb_chat_agentic.reflection import (
    dispatch_subqueries,
    kb_retrieve_context,
    merge_subquery_context,
    retrieve_subquery_context,
)
from app.agents.kb_chat_agentic_state import (
    CompressContextInput,
    KbChatInternalState,
    RetrievalBudgetPlanInput,
)
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.core.settings import Settings
from app.prompts import get_prompt_loader
from app.services.kb_evidence import (
    build_evidence_context,
    canonicalize_evidence_items,
)
from app.services.query_rewrite_service import (
    QueryRewriteService,
    coerce_structured_result_payload,
)
from app.utils.token_counter import count_tokens_approximately

_EVIDENCE_LABEL_RE = re.compile(r"\[[^\[\]\n]{1,128}\]")
_BLANK_LINE_RE = re.compile(r"\n{2,}")


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _resolve_query_count(state: dict[str, Any]) -> int:
    query_items = state.get("query_items")
    if not isinstance(query_items, list):
        return 1
    count = sum(
        1 for item in query_items if isinstance(item, dict) and str(item.get("query") or "").strip()
    )
    return max(1, count)


def _budget_by_complexity(complexity: str) -> tuple[int, int, int]:
    if complexity == "complex":
        return 15, 100, 30
    if complexity == "moderate":
        return 10, 50, 20
    return 5, 20, 10


def _fallback_retrieval_budget(
    state: RetrievalBudgetPlanInput,
    settings: Settings,
) -> tuple[dict[str, int], dict[str, Any]]:
    complexity = str(state.get("complexity_level") or "simple")
    query_count = _resolve_query_count(state)
    per_query_top_k, global_candidates_limit, rerank_input_limit = _budget_by_complexity(
        complexity
    )
    reflection = state.get("reflection")
    failure_reason = (
        str(reflection.get("reason") or "").strip().lower()
        if isinstance(reflection, dict)
        else ""
    )
    if failure_reason in {"no_evidence", "insufficient", "low_overlap", "retry"}:
        per_query_top_k += 2
        global_candidates_limit += 12
        rerank_input_limit += 8
    elif failure_reason == "severe_conflict":
        per_query_top_k += 1
        global_candidates_limit += 16
        rerank_input_limit += 12
    elif failure_reason == "conflict_retry_exhausted":
        rerank_input_limit += 6

    loop_counts = state.get("loop_counts")
    retry_count = (
        int(loop_counts.get("retrieval_retries") or 0)
        if isinstance(loop_counts, dict)
        else 0
    )
    if retry_count > 0:
        per_query_top_k = per_query_top_k + retry_count
        global_candidates_limit = global_candidates_limit + retry_count * 10
        rerank_input_limit = rerank_input_limit + retry_count * 8

    max_top_k = int(settings.retrieval_max_top_k)
    per_query_top_k = max(1, min(per_query_top_k, max_top_k))
    rerank_input_limit = max(
        per_query_top_k,
        min(rerank_input_limit, max(global_candidates_limit, max_top_k * 4)),
    )
    global_candidates_limit = max(
        rerank_input_limit,
        min(global_candidates_limit, max_top_k * 6),
    )

    return (
        {
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
        },
        {
            "complexity": complexity,
            "query_count": query_count,
            "failure_reason": failure_reason or None,
            "retry_count": retry_count,
        },
    )


def _merge_retrieval_plan_summary(
    state: RetrievalBudgetPlanInput,
    *,
    budget: dict[str, int],
    diagnostics: dict[str, Any],
    decision_source: str = "llm",
    fallback_reason: str | None = None,
    fallback_used: bool = False,
    reasoning: str | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "retrieval_plan": {
            **diagnostics,
            **budget,
            "decision_source": decision_source,
            "fallback_reason": fallback_reason,
            "fallback_used": fallback_used,
            "reasoning": reasoning or "",
            "latency_ms": latency_ms,
            "completed_at": now_iso(),
        },
    }
    return stage_summaries


async def _retrieval_plan_node(
    state: RetrievalBudgetPlanInput,
    runtime: Runtime[KbChatGraphContext],
    settings: Settings,
) -> dict[str, Any]:
    _ = runtime
    start = time.perf_counter()
    fallback_budget, diagnostics = _fallback_retrieval_budget(state, settings)
    query = _resolve_query_text(state)
    try:
        planner = QueryRewriteService(settings=settings)
        result = await planner.plan_retrieval_budget(
            question=query,
            normalized_query=query,
            complexity_level=str(diagnostics.get("complexity") or "simple"),
            query_items=state.get("query_items") if isinstance(state.get("query_items"), list) else [],
            retry_count=int(diagnostics.get("retry_count") or 0),
            failure_reason=str(diagnostics.get("failure_reason") or ""),
            max_top_k=int(settings.retrieval_max_top_k),
            fallback_budget=fallback_budget,
        )
        budget = result.budget if isinstance(result.budget, dict) else fallback_budget
        meta = result.meta if isinstance(result.meta, dict) else {}
        fallback_reason = str(meta.get("fallback_reason") or result.reason or "") or None
        fallback_used = bool(meta.get("fallback_used")) or bool(fallback_reason)
        reasoning = str(meta.get("reasoning") or "")
    except Exception:
        budget = fallback_budget
        fallback_reason = "planner_invoke_failed"
        fallback_used = True
        reasoning = ""

    stage_summaries = _merge_retrieval_plan_summary(
        state,
        budget=budget,
        diagnostics=diagnostics,
        decision_source="llm",
        fallback_reason=fallback_reason,
        fallback_used=fallback_used,
        reasoning=reasoning,
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return {
        "retrieval_budget": budget,
        "stage_summaries": stage_summaries,
    }


def _retrieval_budget_plan(
    state: RetrievalBudgetPlanInput,
    settings: Settings,
) -> dict[str, Any]:
    budget, diagnostics = _fallback_retrieval_budget(state, settings)
    stage_summaries = _merge_retrieval_plan_summary(
        state,
        budget=budget,
        diagnostics=diagnostics,
        decision_source="llm",
        fallback_reason="sync_fallback",
        fallback_used=True,
        reasoning="",
        latency_ms=0,
    )
    return {
        "retrieval_budget": budget,
        "stage_summaries": stage_summaries,
    }


def _resolve_query_text(state: dict[str, Any]) -> str:
    for key in (
        "normalized_query",
        "resolved_query",
        "coref_query",
        "rewrite_input_query",
        "user_input",
    ):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _ordered_verbatim_subset(parts: list[str], source: str) -> bool:
    cursor = 0
    for part in parts:
        position = source.find(part, cursor)
        if position < 0:
            return False
        cursor = position + len(part)
    return True


def _is_verbatim_subset(candidate_excerpt: str, source_excerpt: str) -> bool:
    candidate = _normalize_newlines(candidate_excerpt).strip()
    source = _normalize_newlines(source_excerpt)
    if not candidate or not source:
        return False
    if candidate in source:
        return True

    paragraph_parts = [
        part for part in _BLANK_LINE_RE.split(candidate) if part.strip()
    ]
    if len(paragraph_parts) > 1 and _ordered_verbatim_subset(paragraph_parts, source):
        return True

    line_parts = [line for line in candidate.split("\n") if line.strip()]
    return len(line_parts) > 1 and _ordered_verbatim_subset(line_parts, source)


def _coerce_context_compress_decision(
    value: object,
) -> tuple[ContextCompressDecision | None, str | None]:
    if isinstance(value, ContextCompressDecision):
        return value, None
    try:
        return ContextCompressDecision.model_validate(value), None
    except ValidationError:
        return None, "invalid_schema"


async def _compress_context(
    state: CompressContextInput,
    runtime: Runtime[KbChatGraphContext],
    *,
    settings: Settings,
    chat_model: BaseChatModel,
) -> dict[str, Any]:
    _ = runtime, settings
    start = time.perf_counter()
    raw_context = str(state.get("final_context") or "").strip()
    current_evidence_items, current_citation_catalog = canonicalize_evidence_items(
        state.get("evidence_items"),
        citation_catalog=state.get("citation_catalog"),
    )
    final_context = (
        build_evidence_context(current_evidence_items)
        if current_evidence_items
        else (raw_context or "（未找到相关内容）")
    )
    question = _resolve_query_text(state)
    input_tokens = count_tokens_approximately(final_context)

    compressed_context = final_context
    compressed_evidence_items = list(current_evidence_items)
    compressed_citation_catalog = dict(current_citation_catalog)
    fallback_reason: str | None = None
    fallback_used = False
    candidate_citation_ids: list[str] = []
    invalid_citation_ids: list[str] = []
    decision: ContextCompressDecision | None = None

    if final_context and question:
        prompts = get_prompt_loader()
        try:
            compress_system = prompts.render_with_few_shot("kb_chat/context_compress")
        except KeyError:
            compress_system = (
                "你是知识库证据压缩器。"
                "请围绕用户问题压缩参考内容，只保留回答问题所必需且可追溯的事实。"
                "必须保留原有引用标签、数字、时间、范围、比较对象、否定/例外、条件前提。"
                "禁止新增事实，禁止编造或改写引用标签，输出 JSON。"
            )
        compress_user = (
            "请压缩以下知识库参考内容，并按 JSON 合同返回。\n"
            "要求：\n"
            "1) 仅保留与问题直接相关、且对回答必需的证据；\n"
            "2) 必须保留原始引用标签，如 [S1]、[S2]；\n"
            "3) 必须保留关键数字、时间、范围、单位、阈值、比较对象、因果/前提、例外与否定；\n"
            "4) 不得新增参考内容之外的事实；\n"
            "5) excerpt 必须是参考内容中的原文连续片段，不得改写；\n"
            "6) 如果原文已经足够精炼，可返回 keep_all；\n"
            "7) 如果全部参考内容都与问题无关，可返回 no_evidence；\n"
            "8) 不要输出解释、标题、总结性前言或 Markdown 代码块。\n\n"
            f"问题：{question}\n\n"
            f"参考内容：\n{final_context}"
        )
        try:
            structured_model = chat_model.with_structured_output(
                ContextCompressDecision,
                method="function_calling",
                include_raw=True,
            )
            result = await structured_model.ainvoke(
                [
                    SystemMessage(content=compress_system),
                    HumanMessage(content=compress_user),
                ]
            )

            payload, payload_error = coerce_structured_result_payload(
                result=result,
                schema=ContextCompressDecision,
            )
            if payload is None:
                fallback_reason = payload_error or "empty_structured_response"
            else:
                decision, decision_error = _coerce_context_compress_decision(payload)
                fallback_reason = decision_error

            if fallback_reason is None and decision is None:
                fallback_reason = "empty_structured_response"

            if isinstance(decision, ContextCompressDecision) and decision.decision == "no_evidence":
                compressed_context = "（未找到相关内容）"
                compressed_evidence_items = []
                compressed_citation_catalog = {}
            elif isinstance(decision, ContextCompressDecision) and decision.decision == "keep_all":
                compressed_context = final_context
                compressed_evidence_items = list(current_evidence_items)
                compressed_citation_catalog = dict(current_citation_catalog)
                candidate_citation_ids = list(current_citation_catalog)
            elif isinstance(decision, ContextCompressDecision):
                candidate_citation_ids = list(
                    dict.fromkeys(item.citation_id.strip().upper() for item in decision.items)
                )
                if not candidate_citation_ids:
                    fallback_reason = "empty_compress_output"
                else:
                    by_citation_id = {
                        str(item.get("citation_id") or "").strip().upper(): item
                        for item in current_evidence_items
                    }
                    invalid_citation_ids = [
                        citation_id
                        for citation_id in candidate_citation_ids
                        if citation_id not in current_citation_catalog
                    ]
                    if invalid_citation_ids:
                        fallback_reason = "invalid_compressed_citation_labels"
                    else:
                        rebuilt_items: list[dict[str, Any]] = []
                        for selected in decision.items:
                            citation_id = selected.citation_id.strip().upper()
                            excerpt = _normalize_newlines(selected.excerpt).strip()
                            source_item = by_citation_id.get(citation_id)
                            if not isinstance(source_item, dict) or not _is_verbatim_subset(
                                excerpt,
                                str(source_item.get("excerpt") or ""),
                            ):
                                fallback_reason = "non_verbatim_subset"
                                break
                            rebuilt_items.append(
                                {
                                    **source_item,
                                    "citation_id": citation_id,
                                    "excerpt": excerpt,
                                }
                            )

                        if fallback_reason is None:
                            rebuilt_items, rebuilt_catalog = canonicalize_evidence_items(
                                rebuilt_items,
                                citation_catalog=current_citation_catalog,
                            )
                            candidate_context = build_evidence_context(rebuilt_items)
                            if count_tokens_approximately(candidate_context) > input_tokens:
                                fallback_reason = "non_compacting_output"
                            else:
                                compressed_evidence_items = rebuilt_items
                                compressed_citation_catalog = rebuilt_catalog
                                compressed_context = candidate_context
        except asyncio.CancelledError:
            raise
        except Exception:
            fallback_reason = "compress_invoke_failed"
    else:
        fallback_reason = "compress_input_missing"

    if fallback_reason is not None:
        fallback_used = True
        compressed_context = final_context
        compressed_evidence_items = list(current_evidence_items)
        compressed_citation_catalog = dict(current_citation_catalog)

    output_tokens = count_tokens_approximately(compressed_context)
    evidence_count = (
        len(compressed_evidence_items)
        if compressed_evidence_items
        else len(_EVIDENCE_LABEL_RE.findall(compressed_context))
    )
    summary = {
        "decision_source": "llm",
        "fallback_reason": fallback_reason,
        "fallback_used": fallback_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "truncated": output_tokens < input_tokens,
        "evidence_count": evidence_count,
        "candidate_citation_ids": candidate_citation_ids,
        "invalid_citation_ids": invalid_citation_ids,
        "selected_citation_ids": list(compressed_citation_catalog),
        "question_present": bool(question),
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "completed_at": now_iso(),
    }
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "context_compress": summary,
    }
    return {
        "compression_stats": summary,
        "final_context": compressed_context,
        "evidence_items": compressed_evidence_items,
        "citation_catalog": compressed_citation_catalog,
        "stage_summaries": stage_summaries,
    }


def build_retrieval_subgraph(
    *,
    settings: Settings,
    kb_tool: BaseTool,
    chat_model: BaseChatModel,
):
    """Compile retrieval subgraph aligned to flowchart Stage 4."""

    graph = StateGraph(
        state_schema=KbChatInternalState,
        context_schema=KbChatGraphContext,
    )
    retrieval_retry_policy = RetryPolicy(
        max_attempts=max(2, int(getattr(settings, "kb_chat_max_retrieval_retries", 2)) + 1)
    )

    def add_traced_node(
        node_id: str,
        node_callable: Any,
        *,
        side_effect_type: str,
        retry_policy: RetryPolicy | None = None,
        retry_disabled_reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        metadata = extend_kb_chat_node_metadata(
            node_id,
            side_effect_type=side_effect_type,
            retry_enabled=retry_policy is not None,
        )
        if retry_policy is None:
            metadata["retry_disabled_reason"] = retry_disabled_reason or side_effect_type
        graph.add_node(
            node_id,
            wrap_kb_chat_node_with_io(node_id, node_callable),
            metadata=metadata,
            retry_policy=retry_policy,
            **kwargs,
        )

    add_traced_node(
        "retrieval_plan",
        partial(_retrieval_plan_node, settings=settings),
        side_effect_type="llm",
    )
    add_traced_node(
        "dispatch_subqueries",
        partial(dispatch_subqueries, settings=settings),
        side_effect_type="deterministic_rule",
        destinations=("retrieve_subquery", "retrieve"),
    )
    add_traced_node(
        "retrieve_subquery",
        partial(retrieve_subquery_context, settings=settings, kb_tool=kb_tool),
        side_effect_type="external_io",
        retry_policy=retrieval_retry_policy,
    )
    add_traced_node(
        "merge_subquery_context",
        partial(merge_subquery_context, settings=settings),
        side_effect_type="deterministic_rule",
    )
    add_traced_node(
        "retrieve",
        partial(kb_retrieve_context, settings=settings, kb_tool=kb_tool),
        side_effect_type="external_io",
        retry_policy=retrieval_retry_policy,
    )
    add_traced_node(
        "context_compress",
        lambda s, runtime: _compress_context(
            s,
            runtime,
            settings=settings,
            chat_model=chat_model,
        ),
        side_effect_type="llm",
    )

    graph.set_entry_point("retrieval_plan")
    graph.add_edge("retrieval_plan", "dispatch_subqueries")
    graph.add_edge("retrieve_subquery", "merge_subquery_context")
    graph.add_edge("merge_subquery_context", "context_compress")
    graph.add_edge("retrieve", "context_compress")
    graph.add_edge("context_compress", END)
    return graph.compile(name="kb_chat_retrieval_subgraph")
