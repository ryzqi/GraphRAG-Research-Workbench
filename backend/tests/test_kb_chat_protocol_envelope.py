from __future__ import annotations

import uuid

import pytest

from app.services.kb_chat_service import KbChatService


@pytest.mark.parametrize(
    ("event_type", "with_node"),
    [
        ("meta", False),
        ("messages", True),
        ("updates", True),
        ("node_io", True),
        ("ui_event", False),
        ("final", False),
        ("error", False),
        ("interrupt", False),
    ],
)
def test_protocol_envelope_v2_contains_required_fields(
    event_type: str,
    with_node: bool,
) -> None:
    run_id = uuid.uuid4()
    payload = {"ts": "2026-01-01T00:00:00+00:00", "payload": event_type}
    node = {"id": "n1", "name": "node-1"} if with_node else None
    event = KbChatService._build_protocol_event_payload(
        event_type=event_type,
        run_id=run_id,
        payload=payload,
        node=node,
        event_id=f"{run_id}:1",
        seq=1,
        attempt=1 if with_node else None,
        node_path=["node-1"] if with_node else [],
    )
    assert event["version"] == "2.0"
    assert event["type"] == event_type
    assert event["event_id"] == f"{run_id}:1"
    assert event["seq"] == 1
    assert isinstance(event["ts"], str)
    assert event["run"]["id"] == str(run_id)
    assert "attempt" in event
    assert isinstance(event["node_path"], list)
    if with_node:
        assert event["node"]["id"] == "n1"
        assert event["node"]["name"] == "node-1"
