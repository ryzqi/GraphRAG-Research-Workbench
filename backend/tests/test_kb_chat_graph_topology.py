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
