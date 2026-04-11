from __future__ import annotations

from app.services.general_chat_service_interrupts import (
    _build_interrupt_entries,
    _extract_pending_interrupts,
)


def test_extract_pending_interrupts_flattens_nested_interrupt_payloads() -> None:
    pending_writes = [
        ("checkpoint", "__interrupt__", [{"id": "a1", "value": {"message": "need approval", "action_requests": [{"name": "web_search"}]}}]),
        ("checkpoint", "messages", {"ignored": True}),
        ("checkpoint", "__interrupt__", {"id": "a2", "value": {"message": "need approval 2", "action_requests": [{"name": "fetch_url"}]}}),
    ]

    interrupts = _extract_pending_interrupts(pending_writes)

    assert len(interrupts) == 2
    entries = _build_interrupt_entries(interrupts)
    assert [item["interrupt_id"] for item in entries] == ["a1", "a2"]
    assert entries[0]["message"] == "need approval"
    assert entries[1]["action_requests"][0]["name"] == "fetch_url"