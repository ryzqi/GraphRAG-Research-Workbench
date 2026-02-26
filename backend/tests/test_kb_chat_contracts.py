from __future__ import annotations

import pytest

from app.agents.kb_chat_contracts import (
    ContractViolationError,
    EVENT_ENVELOPE_V2,
    ROUTING_TRUTH_TABLE,
    STATE_SCHEMA_V1,
    STATE_SCHEMA_V2,
    STATE_SCHEMA_V3,
    detect_event_protocol_version,
    detect_state_schema_version,
    validate_event_envelope_v2,
    validate_state_write_access,
)


def test_detect_state_schema_version_prefers_explicit_version() -> None:
    assert (
        detect_state_schema_version({"schema_version": STATE_SCHEMA_V3}) == STATE_SCHEMA_V3
    )


def test_detect_state_schema_version_handles_legacy_shapes() -> None:
    assert detect_state_schema_version({"query_bundle": {}}) == STATE_SCHEMA_V2
    assert detect_state_schema_version({"messages": []}) == STATE_SCHEMA_V1


def test_detect_event_protocol_version_is_v2_only() -> None:
    assert detect_event_protocol_version({"type": "updates"}) == "v2"
    assert detect_event_protocol_version({"version": EVENT_ENVELOPE_V2}) == "v2"


def test_validate_event_envelope_v2_reports_missing_required_fields() -> None:
    with pytest.raises(ContractViolationError, match="event_id"):
        validate_event_envelope_v2(
            {
                "version": EVENT_ENVELOPE_V2,
                "type": "updates",
                "seq": 1,
                "ts": "2026-01-01T00:00:00+00:00",
                "run": {"id": "run-1"},
                "attempt": None,
                "node_path": [],
            }
        )


def test_validate_event_envelope_v2_accepts_node_scoped_event() -> None:
    validate_event_envelope_v2(
        {
            "version": EVENT_ENVELOPE_V2,
            "type": "node_io",
            "event_id": "evt-1",
            "seq": 1,
            "ts": "2026-01-01T00:00:00+00:00",
            "run": {"id": "run-1"},
            "attempt": 1,
            "node_path": ["answer_subgraph"],
            "node": {"id": "answer_subgraph", "name": "answer_subgraph"},
        }
    )


def test_validate_state_write_access_rejects_unauthorized_writer() -> None:
    with pytest.raises(ContractViolationError, match="rewrite_plan"):
        validate_state_write_access(field="rewrite_plan", writer="generate")


def test_routing_truth_table_covers_terminal_routes() -> None:
    destinations = {row.destination for row in ROUTING_TRUTH_TABLE}
    assert {"clarify", "transform_query", "finalize", "force_exit"} <= destinations


def test_routing_truth_table_preprocess_ready_goes_to_retrieval_subgraph() -> None:
    target = next(
        (
            row.destination
            for row in ROUTING_TRUTH_TABLE
            if row.source == "preprocess_subgraph" and row.condition == "ready"
        ),
        None,
    )
    assert target == "retrieval_subgraph"
