from __future__ import annotations

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph


class _DummyKbRetrieveTool:
    name = "kb_retrieve"

    async def ainvoke(self, payload: dict):
        _ = payload
        return "[S1] evidence"


def _collect_complexity_targets(graph_json: dict) -> set[str]:
    edges = graph_json.get("edges")
    if not isinstance(edges, list):
        return set()
    targets: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("source") != "complexity_router":
            continue
        target = edge.get("target")
        if isinstance(target, str) and target:
            targets.add(target)
    return targets


def _collect_dispatch_targets(graph_json: dict) -> set[str]:
    edges = graph_json.get("edges")
    if not isinstance(edges, list):
        return set()
    targets: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("source") != "dispatch_subqueries":
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


def test_complexity_router_destinations_without_hyde():
    graph = KbChatAgenticGraph(
        chat_model=object(),  # not used during topology construction
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={"ambiguity_check_enabled": False, "hyde_enabled": False},
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
        kb_chat_config={"ambiguity_check_enabled": False, "hyde_enabled": True},
    )

    graph_json = graph.compile().get_graph().to_json()
    labels = _collect_node_labels(graph_json)

    assert labels["merge_context"] == "\u4e0a\u4e0b\u6587\u5408\u5e76"
    assert labels["complexity_router"] == "\u590d\u6742\u5ea6\u8def\u7531"
    assert labels["retrieve"] == "\u77e5\u8bc6\u68c0\u7d22"
    assert labels["generate"] == "\u7b54\u6848\u751f\u6210"


def test_complexity_router_destinations_with_hyde():
    graph = KbChatAgenticGraph(
        chat_model=object(),  # not used during topology construction
        tools=[_DummyKbRetrieveTool()],
        tool_meta_by_name={},
        kb_chat_config={"ambiguity_check_enabled": False, "hyde_enabled": True},
    )

    graph_json = graph.compile().get_graph().to_json()
    targets = _collect_complexity_targets(graph_json)

    assert targets == {"decomposition", "generate_variants", "hyde"}
    dispatch_targets = _collect_dispatch_targets(graph_json)
    assert dispatch_targets == {"retrieve_subquery", "retrieve"}
