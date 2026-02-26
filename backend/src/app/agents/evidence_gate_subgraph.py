"""Evidence gate subgraph entrypoint for KB Chat v3 rollout."""

from __future__ import annotations

from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.kb_chat_agentic.reflection import doc_gate_precheck
from app.agents.kb_chat_agentic_state import KbChatAgenticState
from app.core.settings import Settings


class KbChatGraphContext(TypedDict, total=False):
    thread_id: str
    user_id: str
    kb_ids: list[str]
    runtime_config: dict[str, Any]
    message_budget: dict[str, Any]


def build_evidence_gate_subgraph(*, settings: Settings):
    """Compile an evidence-gate-only subgraph entrypoint."""

    graph = StateGraph(
        state_schema=KbChatAgenticState,
        context_schema=KbChatGraphContext,
    )
    graph.add_node("doc_gate_precheck", partial(doc_gate_precheck, settings=settings))
    graph.set_entry_point("doc_gate_precheck")
    graph.add_edge("doc_gate_precheck", END)
    return graph.compile(name="kb_chat_evidence_gate_subgraph")
