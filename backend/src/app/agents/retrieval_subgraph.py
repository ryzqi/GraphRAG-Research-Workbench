"""Retrieval subgraph entrypoint for KB Chat v3 rollout."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langchain.tools import BaseTool
from langgraph.graph import END, StateGraph

from app.agents.kb_chat_agentic.reflection import kb_retrieve_context
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def build_retrieval_subgraph(*, settings: Settings, kb_tool: BaseTool):
    """Compile a retrieval-only subgraph entrypoint."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatGraphContext,
    )
    graph.add_node(
        "retrieve",
        partial(kb_retrieve_context, settings=settings, kb_tool=kb_tool),
    )
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", END)
    return graph.compile(name="kb_chat_retrieval_subgraph")
