from __future__ import annotations

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph
from app.services.kb_chat_service import KbChatService


class _DummyKbRetrieveTool:
    name = "kb_retrieve"

    async def ainvoke(self, payload: dict):
        _ = payload
        return "[S1] evidence"


def _collect_targets(graph_json: dict, source: str) -> set[str]:
    edges = graph_json.get("edges")
    if not isinstance(edges, list):
        return set()
    targets: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("source") != source:
            continue
        target = edge.get("target")
        if isinstance(target, str) and target:
            targets.add(target)
    return targets


def _collect_node_labels(graph_json: dict) -> dict[str, str]:
    nodes = graph_json.get("nodes")
    if not isinstance(nodes, list):
        return {}
    labels: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        metadata = node.get("metadata")
        if not isinstance(node_id, str) or not isinstance(metadata, dict):
            continue
        label = metadata.get("label")
        if isinstance(label, str) and label:
            labels[node_id] = label
    return labels


def test_main_graph_orchestrates_only_subgraphs():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": False,
        },
    )

    builder = graph._graph_builder
    node_ids = set(builder.nodes.keys())
    assert {"preprocess_subgraph", "retrieval_subgraph", "evidence_gate_subgraph"} <= node_ids
    assert "merge_context" not in node_ids
    assert ("retrieval_subgraph", "evidence_gate_subgraph") in builder.edges
    assert ("transform_query", "retrieval_subgraph") in builder.edges


def test_graph_node_labels_are_chinese():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": True,
        },
    )

    graph_json = KbChatService._build_drawable_graph_from_builder(graph)
    labels = _collect_node_labels(graph_json)

    assert labels["preprocess_subgraph"] == "\u9884\u5904\u7406\u5b50\u56fe"
    assert labels["retrieval_subgraph"] == "\u68c0\u7d22\u5b50\u56fe"
    assert labels["evidence_gate_subgraph"] == "\u8bc1\u636e\u95e8\u63a7\u5b50\u56fe"
    assert labels["answer_subgraph"] == "\u7b54\u6848\u5b50\u56fe"


def test_make_run_context_includes_message_budget():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": True,
        },
    )

    context = graph.make_run_context(
        thread_id="thread-x",
        state={
            "memory_keys": {"user_id": "u1", "thread_id": "t1", "kb_ids": ["kb1"]},
            "runtime_config": {
                "parallel_retrieval_max_branches": 4,
                "parallel_retrieval_min_queries": 2,
                "parallel_retrieval_include_main": False,
            },
        },
    )

    assert context["thread_id"] == "thread-x"
    assert context["user_id"] == "u1"
    assert context["kb_ids"] == ["kb1"]
    assert context["message_budget"]["max_candidates"] == 4
    assert context["message_budget"]["min_queries"] == 2
    assert context["message_budget"]["include_main"] is False


def test_v3_route_targets_are_stable():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": False,
        },
    )
    graph_json = KbChatService._build_drawable_graph_from_builder(graph)

    assert _collect_targets(graph_json, "preprocess_subgraph") == {
        "retrieval_subgraph",
        "force_exit",
    }
    assert _collect_targets(graph_json, "evidence_gate_subgraph") == {
        "answer_subgraph",
        "transform_query",
        "force_exit",
    }
    assert _collect_targets(graph_json, "answer_subgraph") == {
        "finalize",
        "transform_query",
        "force_exit",
    }
