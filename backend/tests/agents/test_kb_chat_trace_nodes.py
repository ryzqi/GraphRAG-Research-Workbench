from __future__ import annotations

import pytest

from app.agents import kb_chat_trace_nodes


def test_build_event_base_payload_promotes_langgraph_task_id_to_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kb_chat_trace_nodes,
        "get_config",
        lambda: {"configurable": {"__pregel_task_id": "task-123"}},
    )

    payload = kb_chat_trace_nodes._build_event_base_payload("retrieve_subquery")

    assert payload == {
        "event_type": "node_io",
        "node_name": "retrieve_subquery",
        "node_id": "retrieve_subquery",
        "task_id": "task-123",
        "execution_id": "task-123",
    }


def test_query_plan_metadata_replaces_retired_preprocess_enhancement_nodes() -> None:
    metadata = kb_chat_trace_nodes.KB_CHAT_NODE_METADATA

    assert metadata["query_plan"]["label"] == "查询规划"
    assert metadata["query_plan"]["phase"] == "route"
    assert metadata["query_plan_finalize"]["label"] == "查询定稿"
    assert {
        "decomposition",
        "generate_variants",
        "entity_expand",
        "hyde",
        "query_plan_finalize",
    }.issubset(metadata)
    assert {
        "complexity_classify",
        "generate_variants_mod",
        "prepare_messages",
    }.isdisjoint(metadata)
