"""KB Chat v3 的状态、路由与流式封装契约。"""

from __future__ import annotations

from typing import Any, Literal, Mapping

EVENT_ENVELOPE_V2 = "event_envelope_v2"
STATE_SCHEMA_V3 = "kb_chat_state_v3"

NodeScopedEventType = Literal[
    "messages",
    "updates",
    "node_io",
    "step",
    "ui_event",
    "final",
    "error",
    "interrupt",
]

NODE_SCOPED_EVENT_TYPES: set[str] = {
    "messages",
    "updates",
    "node_io",
    "step",
}

KbChatCustomEventType = Literal[
    "node_io",
    "answer_review_subcheck",
    "answer_review_fused",
    "guardrail_warning",
    "heartbeat",
]

KB_CHAT_CUSTOM_EVENT_TYPES: set[str] = {
    "node_io",
    "answer_review_subcheck",
    "answer_review_fused",
    "guardrail_warning",
    "heartbeat",
}


class ContractViolationError(ValueError):
    """契约校验失败时抛出。"""


def detect_event_protocol_version(event: Mapping[str, Any]) -> str:
    version = event.get("version")
    if version == EVENT_ENVELOPE_V2:
        return "v2"
    if isinstance(version, str) and version.startswith("2"):
        return "v2"
    if "event_id" in event and "seq" in event:
        return "v2"
    return "v2"


def validate_event_envelope_v2(
    event: Mapping[str, Any],
    *,
    strict: bool = True,
) -> dict[str, str]:
    warnings: dict[str, str] = {}

    def add_warning(key: str, message: str) -> None:
        warnings[key] = message

    required = (
        "version",
        "type",
        "event_id",
        "seq",
        "ts",
        "run",
        "attempt",
        "node_path",
    )
    for key in required:
        if key not in event:
            add_warning(key, f"missing required envelope field: {key}")

    if event.get("version") not in {EVENT_ENVELOPE_V2, "2", "2.0"}:
        add_warning("version", "invalid envelope version for v2 payload")
    run_payload = event.get("run")
    if not isinstance(run_payload, Mapping) or not run_payload.get("id"):
        add_warning("run.id", "missing required envelope field: run.id")
    if not isinstance(event.get("node_path"), list):
        add_warning("node_path", "invalid envelope field: node_path must be an array")

    event_type = event.get("type")
    if isinstance(event_type, str) and event_type in NODE_SCOPED_EVENT_TYPES:
        node = event.get("node")
        if not isinstance(node, Mapping):
            add_warning("node", "missing required envelope field: node")
        else:
            if not node.get("id"):
                add_warning("node.id", "missing required envelope field: node.id")
            if not node.get("name"):
                add_warning("node.name", "missing required envelope field: node.name")

    if strict and warnings:
        raise ContractViolationError(next(iter(warnings.values())))
    return warnings
