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
