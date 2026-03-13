"""Preprocess subgraph for KB Chat flowchart Stage 1-3."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

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
    KB_CHAT_NODE_METADATA,
    wrap_kb_chat_node_with_io,
)
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


class _SwitchDecision(TypedDict):
    enabled: bool
    goto: str
    reason: str
    source: str


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
    state: dict[str, Any],
    runtime: Runtime[KbChatGraphContext],
    settings: Settings,
) -> dict[str, Any]:
    result = await complexity_classify(state, settings, runtime=runtime)
    updates = result.update if isinstance(result.update, dict) else {}
    goto = result.goto if isinstance(result.goto, str) else ""
    if goto == "decomposition":
        complexity_level = "complex"
        adaptive_route = "complex_path"
    elif goto == "generate_variants":
        complexity_level = "moderate"
        adaptive_route = "moderate_path"
    else:
        complexity_level = "simple"
        adaptive_route = "simple_path"
    stage_summaries = _merge_stage_summary(
        state,
        updates,
        "complexity_classify",
        {
            "complexity_level": complexity_level,
            "adaptive_route": adaptive_route,
        },
    )
    return {
        **updates,
        "complexity_level": complexity_level,
        "adaptive_route": adaptive_route,
        "stage_summaries": stage_summaries,
    }


def _route_after_ambiguity(state: dict[str, Any]) -> str:
    reflection = state.get("reflection")
    action = (
        str(reflection.get("action") or "").strip().lower()
        if isinstance(reflection, dict)
        else ""
    )
    if action == "clarify":
        return "preprocess_exit"
    return "normalize_rewrite"


def _route_after_adaptive_routing(state: dict[str, Any]) -> str:
    route = state.get("adaptive_route")
    if isinstance(route, str) and route in {
        "simple_path",
        "moderate_path",
        "complex_path",
    }:
        return route
    level = state.get("complexity_level")
    if level == "complex":
        return "complex_path"
    if level == "moderate":
        return "moderate_path"
    return "simple_path"


def _adaptive_routing_node(state: dict[str, Any]) -> dict[str, Any]:
    route = _route_after_adaptive_routing(state)
    stage_summaries = state.get("stage_summaries")
    if not isinstance(stage_summaries, dict):
        stage_summaries = {}
    return {
        "stage_summaries": {
            **stage_summaries,
            "adaptive_routing": {
                "adaptive_route": route,
                "complexity_level": state.get("complexity_level"),
            },
        }
    }


def _resolve_switch_decision(
    state: dict[str, Any],
    settings: Settings,
    *,
    settings_attr: str,
    enabled_goto: str,
    disabled_goto: str,
) -> _SwitchDecision:
    _ = state
    enabled = bool(getattr(settings, settings_attr, True))
    source = f"settings.{settings_attr}"
    reason = "settings_default"
    return {
        "enabled": enabled,
        "goto": enabled_goto if enabled else disabled_goto,
        "reason": reason,
        "source": source,
    }


def _switch_node(
    state: dict[str, Any],
    settings: Settings,
    *,
    summary_key: str,
    settings_attr: str,
    enabled_goto: str,
    disabled_goto: str,
) -> dict[str, Any]:
    decision = _resolve_switch_decision(
        state,
        settings,
        settings_attr=settings_attr,
        enabled_goto=enabled_goto,
        disabled_goto=disabled_goto,
    )
    return {
        "stage_summaries": _merge_stage_summary(
            state,
            {},
            summary_key,
            dict(decision),
        )
    }


def _ambiguity_check_enabled_node(
    state: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    return _switch_node(
        state,
        settings,
        summary_key="AMBIGUITY_CHECK_ENABLED",
        settings_attr="kb_chat_ambiguity_check_enabled",
        enabled_goto="ambiguity_check",
        disabled_goto="normalize_rewrite",
    )


def _simple_path(_: dict[str, Any]) -> Command[str]:
    return Command(goto="prepare_messages")


def _moderate_path(_: dict[str, Any]) -> Command[str]:
    return Command(goto="ENABLE_MULTI_QUERY_MOD")


def _complex_path(_: dict[str, Any]) -> Command[str]:
    return Command(goto="ENABLE_DECOMPOSITION")


def _route_to_ambiguity_check(state: dict[str, Any], settings: Settings) -> str:
    return _resolve_switch_decision(
        state,
        settings,
        settings_attr="kb_chat_ambiguity_check_enabled",
        enabled_goto="ambiguity_check",
        disabled_goto="normalize_rewrite",
    )["goto"]


def _multi_query_mod_enabled_node(
    state: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    return _switch_node(
        state,
        settings,
        summary_key="ENABLE_MULTI_QUERY_MOD",
        settings_attr="kb_chat_multi_query_mod_enabled",
        enabled_goto="generate_variants_mod",
        disabled_goto="prepare_messages",
    )


def _route_to_generate_variants_mod(state: dict[str, Any], settings: Settings) -> str:
    return _resolve_switch_decision(
        state,
        settings,
        settings_attr="kb_chat_multi_query_mod_enabled",
        enabled_goto="generate_variants_mod",
        disabled_goto="prepare_messages",
    )["goto"]


def _decomposition_enabled_node(
    state: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    return _switch_node(
        state,
        settings,
        summary_key="ENABLE_DECOMPOSITION",
        settings_attr="kb_chat_decomposition_enabled",
        enabled_goto="decomposition",
        disabled_goto="ENABLE_MULTI_QUERY",
    )


def _route_to_decomposition(state: dict[str, Any], settings: Settings) -> str:
    return _resolve_switch_decision(
        state,
        settings,
        settings_attr="kb_chat_decomposition_enabled",
        enabled_goto="decomposition",
        disabled_goto="ENABLE_MULTI_QUERY",
    )["goto"]


def _multi_query_enabled_node(
    state: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    return _switch_node(
        state,
        settings,
        summary_key="ENABLE_MULTI_QUERY",
        settings_attr="kb_chat_multi_query_enabled",
        enabled_goto="generate_variants",
        disabled_goto="entity_expand",
    )


def _route_to_generate_variants(state: dict[str, Any], settings: Settings) -> str:
    return _resolve_switch_decision(
        state,
        settings,
        settings_attr="kb_chat_multi_query_enabled",
        enabled_goto="generate_variants",
        disabled_goto="entity_expand",
    )["goto"]


def _hyde_enabled_node(
    state: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    return _switch_node(
        state,
        settings,
        summary_key="ENABLE_HYDE",
        settings_attr="kb_chat_hyde_enabled",
        enabled_goto="hyde",
        disabled_goto="prepare_messages",
    )


def _route_to_hyde(state: dict[str, Any], settings: Settings) -> str:
    return _resolve_switch_decision(
        state,
        settings,
        settings_attr="kb_chat_hyde_enabled",
        enabled_goto="hyde",
        disabled_goto="prepare_messages",
    )["goto"]


async def _prepare_messages_terminal(
    state: dict[str, Any],
    runtime: Runtime[KbChatGraphContext],
    settings: Settings,
) -> dict[str, Any]:
    result = await prepare_messages(state, runtime=runtime, settings=settings)
    if isinstance(result, Command):
        updates = result.update if isinstance(result.update, dict) else {}
        if isinstance(result.goto, str) and result.goto.strip():
            return {**updates, "preprocess_next": result.goto.strip()}
        return updates
    return result if isinstance(result, dict) else {}


def _preprocess_exit(_: dict[str, Any]) -> dict[str, Any]:
    return {}


def build_preprocess_subgraph(*, settings: Settings):
    """Compile preprocess subgraph aligned to flowchart Stage 1-3."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatGraphContext,
    )
    def add_traced_node(node_id: str, node_callable: Any, **kwargs: Any) -> None:
        graph.add_node(
            node_id,
            wrap_kb_chat_node_with_io(node_id, node_callable),
            metadata=KB_CHAT_NODE_METADATA[node_id],
            **kwargs,
        )

    add_traced_node("merge_context", partial(merge_context, settings=settings))
    add_traced_node("coref_rewrite", partial(coref_rewrite, settings=settings))
    add_traced_node(
        "AMBIGUITY_CHECK_ENABLED",
        partial(_ambiguity_check_enabled_node, settings=settings),
    )
    add_traced_node("ambiguity_check", partial(ambiguity_check, settings=settings))
    add_traced_node("normalize_rewrite", partial(normalize_rewrite, settings=settings))
    add_traced_node("complexity_classify", partial(_complexity_classify, settings=settings))
    add_traced_node("adaptive_routing", _adaptive_routing_node)
    add_traced_node("simple_path", _simple_path)
    add_traced_node("moderate_path", _moderate_path)
    add_traced_node("complex_path", _complex_path)
    add_traced_node(
        "ENABLE_MULTI_QUERY_MOD",
        partial(_multi_query_mod_enabled_node, settings=settings),
    )
    add_traced_node("generate_variants_mod", partial(generate_variants, settings=settings))
    add_traced_node(
        "ENABLE_DECOMPOSITION",
        partial(_decomposition_enabled_node, settings=settings),
    )
    add_traced_node("decomposition", partial(decomposition, settings=settings))
    add_traced_node(
        "ENABLE_MULTI_QUERY",
        partial(_multi_query_enabled_node, settings=settings),
    )
    add_traced_node("generate_variants", partial(generate_variants, settings=settings))
    add_traced_node("entity_expand", partial(entity_expand, settings=settings))
    add_traced_node("ENABLE_HYDE", partial(_hyde_enabled_node, settings=settings))
    add_traced_node("hyde", partial(hyde, settings=settings))
    add_traced_node("prepare_messages", partial(_prepare_messages_terminal, settings=settings))
    add_traced_node("preprocess_exit", _preprocess_exit)

    graph.set_entry_point("merge_context")
    graph.add_edge("merge_context", "coref_rewrite")
    graph.add_edge("coref_rewrite", "AMBIGUITY_CHECK_ENABLED")
    graph.add_conditional_edges(
        "AMBIGUITY_CHECK_ENABLED",
        lambda state: _route_to_ambiguity_check(state, settings),
        {
            "ambiguity_check": "ambiguity_check",
            "normalize_rewrite": "normalize_rewrite",
        },
    )
    graph.add_conditional_edges(
        "ambiguity_check",
        _route_after_ambiguity,
        {
            "normalize_rewrite": "normalize_rewrite",
            "preprocess_exit": "preprocess_exit",
        },
    )
    graph.add_edge("normalize_rewrite", "complexity_classify")
    graph.add_edge("complexity_classify", "adaptive_routing")
    graph.add_conditional_edges(
        "adaptive_routing",
        _route_after_adaptive_routing,
        {
            "simple_path": "simple_path",
            "moderate_path": "moderate_path",
            "complex_path": "complex_path",
        },
    )
    graph.add_edge("simple_path", "prepare_messages")
    graph.add_edge("moderate_path", "ENABLE_MULTI_QUERY_MOD")
    graph.add_conditional_edges(
        "ENABLE_MULTI_QUERY_MOD",
        lambda state: _route_to_generate_variants_mod(state, settings),
        {
            "generate_variants_mod": "generate_variants_mod",
            "prepare_messages": "prepare_messages",
        },
    )
    graph.add_edge("generate_variants_mod", "prepare_messages")
    graph.add_edge("complex_path", "ENABLE_DECOMPOSITION")
    graph.add_conditional_edges(
        "ENABLE_DECOMPOSITION",
        lambda state: _route_to_decomposition(state, settings),
        {
            "decomposition": "decomposition",
            "ENABLE_MULTI_QUERY": "ENABLE_MULTI_QUERY",
        },
    )
    graph.add_edge("decomposition", "ENABLE_MULTI_QUERY")
    graph.add_conditional_edges(
        "ENABLE_MULTI_QUERY",
        lambda state: _route_to_generate_variants(state, settings),
        {
            "generate_variants": "generate_variants",
            "entity_expand": "entity_expand",
        },
    )
    graph.add_edge("generate_variants", "entity_expand")
    graph.add_edge("entity_expand", "ENABLE_HYDE")
    graph.add_conditional_edges(
        "ENABLE_HYDE",
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
