"""Retrieval subgraph for KB Chat flowchart Stage 4."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langchain.tools import BaseTool
from langgraph.graph import END, StateGraph

from app.agents.kb_chat_agentic.reflection import (
    dispatch_subqueries,
    kb_retrieve_context,
    merge_subquery_context,
    retrieve_subquery_context,
)
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings
from app.utils.token_counter import count_tokens_approximately


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


def _retrieval_budget_plan(state: dict[str, Any], settings: Settings) -> dict[str, Any]:
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
    elif failure_reason == "high_conflict":
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

    runtime_config = state.get("runtime_config")
    if not isinstance(runtime_config, dict):
        runtime_config = {}
    runtime_config = {
        **runtime_config,
        "retrieval_top_k": max(1, min(per_query_top_k, int(settings.retrieval_max_top_k))),
        "retrieval_rerank_top_k": max(
            1, min(rerank_input_limit, int(settings.retrieval_max_top_k))
        ),
    }

    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "retrieval_budget_plan": {
            "complexity": complexity,
            "query_count": query_count,
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
            "failure_reason": failure_reason or None,
            "retry_count": retry_count,
        },
    }
    return {
        "retrieval_budget": {
            "per_query_top_k": per_query_top_k,
            "global_candidates_limit": global_candidates_limit,
            "rerank_input_limit": rerank_input_limit,
        },
        "runtime_config": runtime_config,
        "stage_summaries": stage_summaries,
    }


def _compress_context(state: dict[str, Any]) -> dict[str, Any]:
    final_context = str(state.get("final_context") or "").strip()
    if not final_context:
        final_context = "（未找到相关内容）"
    token_limit = 2500
    token_count = count_tokens_approximately(final_context)
    compressed = final_context
    truncated = False
    if token_count > token_limit:
        keep_ratio = max(0.1, token_limit / max(token_count, 1))
        keep_chars = max(512, int(len(final_context) * keep_ratio))
        compressed = final_context[:keep_chars].rstrip() + "\n\n（上下文已压缩）"
        truncated = True
    compressed_tokens = count_tokens_approximately(compressed)
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    stage_summaries = {
        **stage_summaries,
        "context_compress": {
            "token_limit": token_limit,
            "input_tokens": token_count,
            "output_tokens": compressed_tokens,
            "truncated": truncated,
        },
    }
    return {
        "compressed_context": compressed,
        "compression_stats": {
            "token_limit": token_limit,
            "input_tokens": token_count,
            "output_tokens": compressed_tokens,
            "truncated": truncated,
        },
        # Keep downstream compatibility: current doc gate reads final_context.
        "final_context": compressed,
        "stage_summaries": stage_summaries,
    }


def build_retrieval_subgraph(*, settings: Settings, kb_tool: BaseTool):
    """Compile retrieval subgraph aligned to flowchart Stage 4."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatGraphContext,
    )
    graph.add_node(
        "retrieval_budget_plan",
        partial(_retrieval_budget_plan, settings=settings),
    )
    graph.add_node(
        "dispatch_subqueries",
        partial(dispatch_subqueries, settings=settings),
        destinations=("retrieve_subquery", "retrieve"),
    )
    graph.add_node(
        "retrieve_subquery",
        partial(retrieve_subquery_context, settings=settings, kb_tool=kb_tool),
    )
    graph.add_node(
        "merge_subquery_context",
        partial(merge_subquery_context, settings=settings),
    )
    graph.add_node(
        "retrieve",
        partial(kb_retrieve_context, settings=settings, kb_tool=kb_tool),
    )
    graph.add_node("context_compress", _compress_context)

    graph.set_entry_point("retrieval_budget_plan")
    graph.add_edge("retrieval_budget_plan", "dispatch_subqueries")
    graph.add_edge("retrieve_subquery", "merge_subquery_context")
    graph.add_edge("merge_subquery_context", "context_compress")
    graph.add_edge("retrieve", "context_compress")
    graph.add_edge("context_compress", END)
    return graph.compile(name="kb_chat_retrieval_subgraph")
