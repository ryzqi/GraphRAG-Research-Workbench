from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import uuid

import pytest

from app.agents.kb_chat_contracts import (
    KB_CHAT_CUSTOM_EVENT_TYPES,
    validate_event_envelope_v2,
)
from app.agents.kb_chat_trace_nodes import (
    REDACTED_STREAM_VALUE,
    TRACE_SNAPSHOT_CHAR_LIMIT,
    sanitize_snapshot_for_stream,
)
from app.api.sse import SseHeartbeatStats, encode_sse
from app.services.kb_chat_service import KbChatService


def test_sanitize_snapshot_for_stream_is_summary_first_and_redacts_sensitive_fields() -> None:
    payload, meta = sanitize_snapshot_for_stream(
        {
            "user_input": "用户问题",
            "token": "secret-token",
            "nested": {
                "api_key": "super-secret",
                "note": "x" * (TRACE_SNAPSHOT_CHAR_LIMIT + 10),
            },
        },
        include_snapshot=False,
    )

    assert payload is None
    assert meta["included"] is False
    assert meta["truncated"] is True
    assert meta["summary"]["keys"] >= 2

    debug_payload, debug_meta = sanitize_snapshot_for_stream(
        {
            "token": "secret-token",
            "nested": {
                "api_key": "super-secret",
                "note": "x" * (TRACE_SNAPSHOT_CHAR_LIMIT + 10),
            },
        },
        include_snapshot=True,
    )

    assert debug_meta["included"] is True
    assert debug_meta["truncated"] is True
    assert debug_payload["token"] == REDACTED_STREAM_VALUE
    assert debug_payload["nested"]["api_key"] == REDACTED_STREAM_VALUE
    assert isinstance(debug_payload["nested"]["note"], str)
    assert len(debug_payload["nested"]["note"]) <= TRACE_SNAPSHOT_CHAR_LIMIT + 32


def test_validate_event_envelope_v2_supports_lenient_drift_report() -> None:
    warnings = validate_event_envelope_v2(
        {
            "version": "2.0",
            "type": "node_io",
            "event_id": "evt-1",
            "seq": 1,
            "ts": "2026-03-13T00:00:00Z",
            "run": {"id": "run-1"},
        },
        strict=False,
    )

    assert warnings
    assert "node_path" in warnings
    assert "node" in warnings


@pytest.mark.asyncio
async def test_encode_sse_emits_heartbeat_when_upstream_is_idle() -> None:
    async def _events():
        await asyncio.sleep(0.02)
        yield "final", {"ok": True}

    frames: list[str] = []
    async for frame in encode_sse(
        _events(),
        heartbeat_interval=0.005,
        heartbeat_factory=lambda: {"type": "heartbeat", "ts": "2026-03-13T00:00:00Z"},
    ):
        frames.append(frame)

    assert any("event: heartbeat" in frame for frame in frames)
    assert any("event: final" in frame for frame in frames)
    heartbeat_frame = next(frame for frame in frames if "event: heartbeat" in frame)
    assert json.loads(heartbeat_frame.split("data: ", 1)[1])["type"] == "heartbeat"


@pytest.mark.asyncio
async def test_encode_sse_tracks_heartbeat_metrics() -> None:
    async def _events():
        await asyncio.sleep(0.02)
        yield "final", {"ok": True}

    heartbeat_stats = SseHeartbeatStats()

    async for _frame in encode_sse(
        _events(),
        heartbeat_interval=0.005,
        heartbeat_factory=lambda: {"type": "heartbeat", "ts": "2026-03-13T00:00:00Z"},
        heartbeat_stats=heartbeat_stats,
    ):
        pass

    assert heartbeat_stats.sent_count >= 1
    assert heartbeat_stats.gap_ms_samples == sorted(heartbeat_stats.gap_ms_samples)


def test_build_protocol_metrics_includes_salvage_truncation_and_heartbeat_stats() -> None:
    service = object.__new__(KbChatService)
    service._settings = SimpleNamespace(
        kb_chat_trace_enabled=False,
        kb_chat_json_safe_policy="stringify",
    )
    heartbeat_stats = SseHeartbeatStats()
    heartbeat_stats.record(now_monotonic=1.0)
    heartbeat_stats.record(now_monotonic=1.02)
    heartbeat_stats.record(now_monotonic=1.04)

    metrics = service._build_protocol_metrics(
        protocol_emit_total=12,
        protocol_required_field_drift_count=3,
        protocol_salvage_count=2,
        node_io_snapshot_truncated_count=4,
        custom_event_unhandled_count=1,
        heartbeat_stats=heartbeat_stats,
    )

    assert metrics == {
        "protocol_emit_total": 12,
        "protocol_required_field_drift_count": 3,
        "protocol_required_field_drift_rate": 25.0,
        "protocol_salvage_count": 2,
        "node_io_snapshot_truncated_count": 4,
        "custom_event_unhandled_count": 1,
        "sse_heartbeat_sent_count": 3,
        "sse_heartbeat_gap_ms_p95": 20.0,
    }


def test_kb_chat_custom_event_taxonomy_is_explicit() -> None:
    assert KB_CHAT_CUSTOM_EVENT_TYPES >= {
        "node_io",
        "answer_review_subcheck",
        "answer_review_fused",
        "guardrail_warning",
        "heartbeat",
    }


def test_build_node_io_payload_preserves_display_contract_fields() -> None:
    run_id = uuid.uuid4()

    payload = KbChatService._build_node_io_payload(
        run_id=run_id,
        node_name="complexity_classify",
        node_id="complexity_classify",
        phase="error",
        attempt=2,
        display_input_items=[
            {"key": "user_input", "label": "用户问题", "value": "解释 CoT 和 ToT 的区别"}
        ],
        display_output_items=[
            {"key": "decision", "label": "结论", "value": "复杂问题"},
            {"key": "reason", "label": "原因", "value": "涉及方法比较与边界说明"},
            {"key": "next_node_label", "label": "下一跳", "value": "问题分解"},
            {"key": "error_summary", "label": "错误信息", "value": "节点执行失败"},
        ],
        error_summary="节点执行失败",
        node_path=["preprocess_subgraph", "complexity_classify"],
    )

    assert payload["display_input_items"] == [
        {"key": "user_input", "label": "用户问题", "value": "解释 CoT 和 ToT 的区别"}
    ]
    assert payload["display_output_items"] == [
        {"key": "decision", "label": "结论", "value": "复杂问题"},
        {"key": "reason", "label": "原因", "value": "涉及方法比较与边界说明"},
        {"key": "next_node_label", "label": "下一跳", "value": "问题分解"},
        {"key": "error_summary", "label": "错误信息", "value": "节点执行失败"},
    ]
    assert payload["error_summary"] == "节点执行失败"
    assert payload["node_path"] == ["preprocess_subgraph", "complexity_classify"]
    assert payload["node"] == {
        "id": "complexity_classify",
        "name": "complexity_classify",
    }
