from __future__ import annotations

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.services.kb_chat_service import KbChatService


class _DummyKbRetrieveTool:
    name = "kb_retrieve"

    async def ainvoke(self, payload: dict):
        _ = payload
        return "[S1] evidence"


def test_build_drawable_graph_from_builder_supports_v3_topology() -> None:
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": False,
            "kb_chat_graph_v3_enabled": True,
        },
    )

    drawable = KbChatService._build_drawable_graph_from_builder(graph)
    assert isinstance(drawable.get("nodes"), list)
    assert isinstance(drawable.get("edges"), list)

    node_ids = {node.get("id") for node in drawable["nodes"] if isinstance(node, dict)}
    assert "preprocess_subgraph" in node_ids
    assert "retrieval_subgraph" in node_ids

    has_conditional_edge = any(
        isinstance(edge, dict)
        and edge.get("source") == "preprocess_subgraph"
        and edge.get("target") == "retrieval_subgraph"
        and edge.get("conditional") is True
        for edge in drawable["edges"]
    )
    assert has_conditional_edge
