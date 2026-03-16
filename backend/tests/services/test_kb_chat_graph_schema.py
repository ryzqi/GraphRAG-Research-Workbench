from __future__ import annotations

from types import SimpleNamespace

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.services.kb_chat_service import KbChatService


def test_graph_schema_payload_includes_hash_and_full_node_metadata() -> None:
    payload = KbChatService._build_graph_schema_payload(
        {
            "nodes": [
                {
                    "id": "retrieve",
                    "metadata": {
                        "label": "知识检索",
                        "phase": "retrieve",
                        "order": 27,
                        "retry_enabled": True,
                    },
                }
            ],
            "edges": [{"source": "retrieve", "target": "context_compress", "conditional": False}],
        },
        config=SimpleNamespace(),
    )

    assert payload["version"] == "1.1"
    assert isinstance(payload["hash"], str)
    assert payload["nodes"][0]["metadata"]["retry_enabled"] is True
    assert payload["nodes"][0]["label"] == "知识检索"


def test_builder_fallback_collects_nested_and_conditional_edges() -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    drawable = KbChatService._build_drawable_graph_from_builder(graph)
    edge_set = {
        (edge["source"], edge["target"], edge["conditional"])
        for edge in drawable["edges"]
    }
    node_ids = {node["id"] for node in drawable["nodes"]}

    assert "preprocess_subgraph" in node_ids
    assert "transform_query" in node_ids
    assert ("preprocess_subgraph", "retrieval_subgraph", True) in edge_set
    assert ("evidence_gate_subgraph", "answer_subgraph", True) in edge_set
    assert ("transform_query", "retrieval_subgraph", False) in edge_set
