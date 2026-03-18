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
    assert "answer_subgraph" in node_ids
    assert "evidence_gate_subgraph" not in node_ids
    assert "confidence_calibrate" not in node_ids
    assert ("preprocess_subgraph", "retrieval_subgraph", True) in edge_set
    assert ("retrieval_subgraph", "answer_subgraph", False) in edge_set
    assert ("transform_query", "retrieval_subgraph", False) in edge_set


def test_compiled_kb_chat_graph_drawable_export_handles_conditional_subgraph_routes() -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    drawable = graph.compile().get_graph().to_json()
    edge_set = {
        (edge["source"], edge["target"], edge.get("conditional", False))
        for edge in drawable["edges"]
    }

    assert ("preprocess_subgraph", "force_exit", True) in edge_set
    assert ("answer_subgraph", "force_exit", True) in edge_set
    assert ("answer_subgraph", "transform_query", True) in edge_set


def test_drawable_graph_omits_pruned_gate_and_verification_nodes() -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    drawable = graph.compile().get_graph().to_json()
    node_ids = {node["id"] for node in drawable["nodes"]}

    assert {
        "evidence_gate_subgraph",
        "doc_gate_sufficiency",
        "doc_gate_route",
        "doc_gate_dispatch",
        "doc_gate_answerability",
        "doc_gate_conflict",
        "doc_gate_fuse",
        "cove_check",
        "chain_of_verification",
        "claim_citation_check",
        "confidence_calibrate",
    }.isdisjoint(node_ids)


def test_schema_drawable_export_falls_back_to_builder_when_compiled_graph_is_truncated() -> None:
    graph = KbChatAgenticGraph(
        chat_model=SimpleNamespace(),
        tools=[SimpleNamespace(name="kb_retrieve")],
        tool_meta_by_name={},
    )

    drawable = KbChatService._build_schema_drawable_graph(graph)
    node_ids = {node["id"] for node in drawable["nodes"]}

    assert "hyde" in node_ids
    assert "entity_expand" in node_ids
    assert "merge_context" in node_ids
