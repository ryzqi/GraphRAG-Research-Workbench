"""Preprocess subgraph for KB Chat flowchart Stage 1-3."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy

from app.agents.kb_chat_agentic.preprocess import (
    ambiguity_check,
    coref_rewrite,
    complexity_classify,
    decomposition,
    entity_expand,
    generate_variants,
    hyde,
    merge_context,
    normalize_rewrite,
    prepare_messages,
)
from app.agents.kb_chat_trace_nodes import (
    extend_kb_chat_node_metadata,
    wrap_kb_chat_node_with_io,
)
from app.agents.kb_chat_agentic_state import (
    ComplexityClassifyInput,
    KbChatEmptyState,
    KbChatInternalState,
    PrepareMessagesInput,
    PreprocessRoutingInput,
    resolve_routing_decision,
)
from app.core.settings import Settings


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def _merge_stage_summary(
    state: dict[str, Any],
    updates: dict[str, Any],
    key: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    stage = state.get("stage_summaries")
    if not isinstance(stage, dict):
        stage = {}
    update_stage = updates.get("stage_summaries")
    if isinstance(update_stage, dict):
        stage = {**stage, **update_stage}
    existing = stage.get(key) if isinstance(stage.get(key), dict) else {}
    return {**stage, key: {**existing, **patch}}


async def _complexity_classify(
    state: ComplexityClassifyInput,
    runtime: Runtime[KbChatGraphContext],
    settings: Settings,
) -> dict[str, Any]:
    result = await complexity_classify(state, settings, runtime=runtime)
    updates = result.update if isinstance(result.update, dict) else {}
    query_strategy = updates.get("query_strategy")
    if query_strategy == "decomposition":
        complexity_level = "complex"
    elif query_strategy == "multi_query":
        complexity_level = "moderate"
    else:
        complexity_level = "simple"
    next_node = _resolve_complexity_next_node(
        query_strategy=query_strategy if isinstance(query_strategy, str) else None,
        settings=settings,
    )
    stage_summaries = _merge_stage_summary(
        state,
        updates,
        "complexity_classify",
        {
            "complexity_level": complexity_level,
            "next_node": next_node,
        },
    )
    return {
        **updates,
        "complexity_level": complexity_level,
        "stage_summaries": stage_summaries,
    }


def _route_after_ambiguity(state: PreprocessRoutingInput) -> str:
    decision = resolve_routing_decision(state, "preprocess")
    if str(decision.get("next_node") or "").strip().lower() == "force_exit":
        return "preprocess_exit"
    return "query_normalize"


def _resolve_complexity_next_node(
    *,
    query_strategy: str | None,
    settings: Settings,
) -> str:
    if query_strategy == "decomposition":
        if bool(getattr(settings, "kb_chat_decomposition_enabled", True)):
            return "decomposition"
        if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
            return "generate_variants"
        return "entity_expand"
    if query_strategy == "multi_query":
        if bool(getattr(settings, "kb_chat_multi_query_mod_enabled", True)):
            return "generate_variants_mod"
        return "prepare_messages"
    return "prepare_messages"


def _route_after_complexity_classify(
    state: dict[str, Any],
    settings: Settings,
) -> str:
    query_strategy = state.get("query_strategy")
    if not isinstance(query_strategy, str):
        level = state.get("complexity_level")
        if level == "complex":
            query_strategy = "decomposition"
        elif level == "moderate":
            query_strategy = "multi_query"
        else:
            query_strategy = "direct"
    return _resolve_complexity_next_node(
        query_strategy=query_strategy,
        settings=settings,
    )


def _route_after_decomposition(
    _: dict[str, Any],
    settings: Settings,
) -> str:
    if bool(getattr(settings, "kb_chat_multi_query_enabled", True)):
        return "generate_variants"
    return "entity_expand"


def _route_to_ambiguity_check(state: KbChatEmptyState, settings: Settings) -> str:
    _ = state
    return (
        "ambiguity_check"
        if bool(getattr(settings, "kb_chat_ambiguity_check_enabled", True))
        else "query_normalize"
    )


def _route_to_hyde(state: KbChatEmptyState, settings: Settings) -> str:
    _ = state
    return (
        "hyde"
        if bool(getattr(settings, "kb_chat_hyde_enabled", True))
        else "prepare_messages"
    )


async def _prepare_messages_terminal(
    state: PrepareMessagesInput,
    runtime: Runtime[KbChatGraphContext],
    settings: Settings,
) -> dict[str, Any]:
    result = await prepare_messages(state, runtime=runtime, settings=settings)
    if isinstance(result, Command):
        updates = result.update if isinstance(result.update, dict) else {}
        return updates
    return result if isinstance(result, dict) else {}


async def _entity_expand_terminal(
    state: dict[str, Any],
    runtime: Runtime[KbChatGraphContext],
    settings: Settings,
) -> dict[str, Any]:
    result = await entity_expand(state, runtime=runtime, settings=settings)
    if isinstance(result, Command):
        updates = result.update if isinstance(result.update, dict) else {}
    else:
        updates = result if isinstance(result, dict) else {}
    next_node = _route_to_hyde(state, settings)
    stage_summaries = _merge_stage_summary(
        state,
        updates,
        "entity_expand",
        {
            "next_node": next_node,
            "hyde_enabled": next_node == "hyde",
        },
    )
    return {
        **updates,
        "stage_summaries": stage_summaries,
    }


def _preprocess_exit(_: KbChatEmptyState) -> dict[str, Any]:
    return {}


def build_preprocess_subgraph(*, settings: Settings):
    """Compile preprocess subgraph aligned to flowchart Stage 1-3."""

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
        "complexity_classify",
        partial(_complexity_classify, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "generate_variants_mod",
        partial(generate_variants, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
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
        partial(_entity_expand_terminal, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "hyde",
        partial(hyde, settings=settings),
        side_effect_type="llm",
        retry_policy=llm_retry_policy,
    )
    add_traced_node(
        "prepare_messages",
        partial(_prepare_messages_terminal, settings=settings),
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
    graph.add_edge("query_normalize", "complexity_classify")
    graph.add_conditional_edges(
        "complexity_classify",
        lambda state: _route_after_complexity_classify(state, settings),
        {
            "prepare_messages": "prepare_messages",
            "generate_variants_mod": "generate_variants_mod",
            "decomposition": "decomposition",
            "generate_variants": "generate_variants",
            "entity_expand": "entity_expand",
        },
    )
    graph.add_edge("generate_variants_mod", "prepare_messages")
    graph.add_conditional_edges(
        "decomposition",
        lambda state: _route_after_decomposition(state, settings),
        {
            "generate_variants": "generate_variants",
            "entity_expand": "entity_expand",
        },
    )
    graph.add_edge("generate_variants", "entity_expand")
    graph.add_conditional_edges(
        "entity_expand",
        lambda state: _route_to_hyde(state, settings),
        {
            "hyde": "hyde",
            "prepare_messages": "prepare_messages",
        },
    )
    graph.add_edge("hyde", "prepare_messages")
    graph.add_edge("prepare_messages", "preprocess_exit")
    graph.add_edge("preprocess_exit", END)
    return graph.compile(name="kb_chat_preprocess_subgraph")
