from __future__ import annotations

import json

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph


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


def _collect_complexity_targets(graph_json: dict) -> set[str]:
    return _collect_targets(graph_json, "complexity_router")


def _collect_dispatch_targets(graph_json: dict) -> set[str]:
    return _collect_targets(graph_json, "dispatch_subqueries")


def _collect_doc_gate_route_targets(graph_json: dict) -> set[str]:
    return _collect_targets(graph_json, "doc_gate_route")


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


def test_complexity_router_destinations_without_hyde():
    graph = KbChatAgenticGraph(
        chat_model=object(),  # not used during topology construction
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": False,
            "kb_chat_graph_v3_enabled": False,
        },
    )

    graph_json = graph.compile().get_graph().to_json()
    targets = _collect_complexity_targets(graph_json)

    assert targets == {"decomposition", "generate_variants", "prepare_messages"}
    dispatch_targets = _collect_dispatch_targets(graph_json)
    assert dispatch_targets == {"retrieve_subquery", "retrieve"}


def test_graph_node_labels_are_chinese():
    graph = KbChatAgenticGraph(
        chat_model=object(),  # not used during topology construction
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": True,
            "kb_chat_graph_v3_enabled": False,
        },
    )

    graph_json = graph.compile().get_graph().to_json()
    labels = _collect_node_labels(graph_json)

    assert labels["merge_context"] == "\u4e0a\u4e0b\u6587\u5408\u5e76"
    assert labels["complexity_router"] == "\u590d\u6742\u5ea6\u8def\u7531"
    assert labels["retrieve"] == "\u77e5\u8bc6\u68c0\u7d22"
    assert labels["answer_subgraph"] == "\u7b54\u6848\u5b50\u56fe"


def test_complexity_router_destinations_with_hyde():
    graph = KbChatAgenticGraph(
        chat_model=object(),  # not used during topology construction
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": True,
            "kb_chat_graph_v3_enabled": False,
        },
    )

    graph_json = graph.compile().get_graph().to_json()
    targets = _collect_complexity_targets(graph_json)

    assert targets == {"decomposition", "generate_variants", "hyde"}
    dispatch_targets = _collect_dispatch_targets(graph_json)
    assert dispatch_targets == {"retrieve_subquery", "retrieve"}


def test_make_run_context_includes_message_budget():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": True,
            "kb_chat_graph_v3_enabled": False,
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


def test_doc_gate_route_destinations():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": False,
            "kb_chat_graph_v3_enabled": False,
        },
    )

    graph_json = graph.compile().get_graph().to_json()
    targets = _collect_doc_gate_route_targets(graph_json)

    assert targets == {"answer_subgraph", "transform_query", "force_exit"}


def test_v3_main_graph_orchestrates_only_subgraphs():
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

    builder = graph._graph_builder
    node_ids = set(builder.nodes.keys())
    assert {"preprocess_subgraph", "retrieval_subgraph", "evidence_gate_subgraph"} <= node_ids
    assert "merge_context" not in node_ids
    assert ("retrieval_subgraph", "evidence_gate_subgraph") in builder.edges
    assert ("transform_query", "retrieval_subgraph") in builder.edges


def test_graph_topology_snapshot_stable_for_core_routes():
    graph = KbChatAgenticGraph(
        chat_model=object(),
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={
            "ambiguity_check_enabled": False,
            "hyde_enabled": False,
            "kb_chat_graph_v3_enabled": False,
        },
    )

    graph_json = graph.compile().get_graph().to_json()
    snapshot = {
        "node_count": len(graph_json.get("nodes") or []),
        "edge_count": len(graph_json.get("edges") or []),
        "core_routes": {
            "complexity_router": sorted(_collect_complexity_targets(graph_json)),
            "dispatch_subqueries": sorted(_collect_dispatch_targets(graph_json)),
            "doc_gate_route": sorted(_collect_doc_gate_route_targets(graph_json)),
            "answer_subgraph": sorted(_collect_targets(graph_json, "answer_subgraph")),
        },
    }
    expected = {
        "node_count": 23,
        "edge_count": 33,
        "core_routes": {
            "complexity_router": [
                "decomposition",
                "generate_variants",
                "prepare_messages",
            ],
            "dispatch_subqueries": ["retrieve", "retrieve_subquery"],
            "doc_gate_route": ["answer_subgraph", "force_exit", "transform_query"],
            "answer_subgraph": ["finalize", "force_exit", "transform_query"],
        },
    }
    assert json.dumps(snapshot, sort_keys=True) == json.dumps(expected, sort_keys=True)
