"""KB Chat v3 contracts for state, routing, and stream envelopes."""

from __future__ import annotations

from typing import Any, Literal, Mapping

EVENT_ENVELOPE_V2 = "event_envelope_v2"
STATE_SCHEMA_V3 = "kb_chat_state_v3"

NodeScopedEventType = Literal[
    "messages",
    "updates",
    "node_io",
    "ui_event",
    "final",
    "error",
    "interrupt",
]

NODE_SCOPED_EVENT_TYPES: set[str] = {
    "messages",
    "updates",
    "node_io",
}


class ContractViolationError(ValueError):
    """Raised when contract validation fails."""


def detect_event_protocol_version(event: Mapping[str, Any]) -> str:
    version = event.get("version")
    if version == EVENT_ENVELOPE_V2:
        return "v2"
    if isinstance(version, str) and version.startswith("2"):
        return "v2"
    if "event_id" in event and "seq" in event:
        return "v2"
    return "v2"
def validate_event_envelope_v2(event: Mapping[str, Any]) -> None:
    required = ("version", "type", "event_id", "seq", "ts", "run", "attempt", "node_path")
    for key in required:
        if key not in event:
            raise ContractViolationError(f"missing required envelope field: {key}")

    if event.get("version") not in {EVENT_ENVELOPE_V2, "2", "2.0"}:
        raise ContractViolationError("invalid envelope version for v2 payload")
    if not isinstance(event.get("run"), Mapping) or not event["run"].get("id"):
        raise ContractViolationError("missing required envelope field: run.id")
    if not isinstance(event.get("node_path"), list):
        raise ContractViolationError("invalid envelope field: node_path must be an array")

    event_type = event.get("type")
    if isinstance(event_type, str) and event_type in NODE_SCOPED_EVENT_TYPES:
        node = event.get("node")
        if not isinstance(node, Mapping):
            raise ContractViolationError("missing required envelope field: node")
        if not node.get("id"):
            raise ContractViolationError("missing required envelope field: node.id")
        if not node.get("name"):
            raise ContractViolationError("missing required envelope field: node.name")
