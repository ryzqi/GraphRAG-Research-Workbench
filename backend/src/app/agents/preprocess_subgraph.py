"""Preprocess subgraph for KB Chat flowchart Stage 1-3."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import RetryPolicy

from app.agents.kb_chat_agentic.preprocess import (
    ambiguity_check,
    coref_rewrite,
    decomposition,
    entity_expand,
    generate_variants,
    hyde,
    merge_context,
    normalize_rewrite,
    query_plan,
    query_plan_finalize,
)
from app.agents.kb_chat_agentic_state import (
    KbChatEmptyState,
    KbChatInternalState,
    PreprocessRoutingInput,
    resolve_routing_decision,
)
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.core.settings import Settings


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _route_after_ambiguity(state: PreprocessRoutingInput) -> str:
    decision = resolve_routing_decision(state, "preprocess")
    if str(decision.get("next_node") or "").strip().lower() == "force_exit":
        return "preprocess_exit"
    return "query_normalize"


def _route_to_ambiguity_check(state: KbChatEmptyState, settings: Settings) -> str:
    _ = state
    return (
        "ambiguity_check"
        if bool(getattr(settings, "kb_chat_ambiguity_check_enabled", True))
        else "query_normalize"
    )


def _route_after_decomposition(_: dict[str, Any], settings: Settings) -> str:
    if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
        return "generate_variants"
    return "entity_expand"


def _route_after_generate_variants(_: dict[str, Any]) -> str:
    return "entity_expand"


def _preprocess_exit(_: KbChatEmptyState) -> dict[str, Any]:
    return {}


def build_preprocess_subgraph(*, settings: Settings):
    """Compile preprocess subgraph aligned to Scheme B live routing."""

    graph = StateGraph(
        state_schema=KbChatInternalState,
        context_schema=KbChatGraphContext,
    )
    llm_retry_policy = RetryPolicy(
        max_attempts=max(2, int(getattr(settings, "kb_chat_max_generation_retries", 2)) + 1)
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
        "merge_context",
        partial(merge_context, settings=settings),
        side_effect_type="context_read",
    )
    add_traced_node(
        "resolve_reference",
        partial(coref_rewrite, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "ambiguity_check",
        partial(ambiguity_check, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "query_normalize",
        partial(normalize_rewrite, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "query_plan",
        partial(query_plan, settings=settings),
        side_effect_type="deterministic_rule",
        destinations={
            "decomposition": "decomposition",
            "generate_variants": "generate_variants",
            "entity_expand": "entity_expand",
            "query_plan_finalize": "query_plan_finalize",
        },
    )
    add_traced_node(
        "decomposition",
        partial(decomposition, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "generate_variants",
        partial(generate_variants, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "entity_expand",
        partial(entity_expand, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
        destinations={
            "hyde": "hyde",
            "query_plan_finalize": "query_plan_finalize",
        },
    )
    add_traced_node(
        "hyde",
        partial(hyde, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "query_plan_finalize",
        partial(query_plan_finalize, settings=settings),
        side_effect_type="deterministic_rule",
    )
    add_traced_node("preprocess_exit", _preprocess_exit, side_effect_type="deterministic_rule")

    graph.set_entry_point("merge_context")
    graph.add_edge("merge_context", "resolve_reference")
    graph.add_conditional_edges(
        "resolve_reference",
        lambda state: _route_to_ambiguity_check(state, settings),
        {
            "ambiguity_check": "ambiguity_check",
            "query_normalize": "query_normalize",
        },
    )
    graph.add_conditional_edges(
        "ambiguity_check",
        _route_after_ambiguity,
        {
            "query_normalize": "query_normalize",
            "preprocess_exit": "preprocess_exit",
        },
    )
    graph.add_edge("query_normalize", "query_plan")
    graph.add_conditional_edges(
        "decomposition",
        lambda state: _route_after_decomposition(state, settings),
        {
            "generate_variants": "generate_variants",
            "entity_expand": "entity_expand",
        },
    )
    graph.add_conditional_edges(
        "generate_variants",
        _route_after_generate_variants,
        {
            "entity_expand": "entity_expand",
        },
    )
    graph.add_edge("hyde", "query_plan_finalize")
    graph.add_edge("query_plan_finalize", "preprocess_exit")
    graph.add_edge("preprocess_exit", END)
    return graph.compile(name="kb_chat_preprocess_subgraph")
