"""Preprocess subgraph entrypoint for KB Chat v3 rollout."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.kb_chat_agentic.preprocess import merge_context
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def build_preprocess_subgraph(*, settings: Settings):
    """Compile a preprocess-only subgraph entrypoint."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatGraphContext,
    )
    graph.add_node("merge_context", partial(merge_context, settings=settings))
    graph.set_entry_point("merge_context")
    graph.add_edge("merge_context", END)
    return graph.compile(name="kb_chat_preprocess_subgraph")
