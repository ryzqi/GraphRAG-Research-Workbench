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
        node_name="query_plan",
        node_id="query_plan",
        phase="error",
        attempt=2,
        display_input_items=[
            {"key": "normalized_query", "label": "规范化问题", "value": "解释 CoT 和 ToT 的区别"}
        ],
        display_output_items=[
            {"key": "query_items", "label": "检索查询项", "value": ["1. [main] 解释 CoT 和 ToT 的区别"]},
            {"key": "reason", "label": "原因", "value": "保留主问题并生成完整检索项"},
            {"key": "next_node_label", "label": "下一跳", "value": "子查询派发"},
            {"key": "error_summary", "label": "错误信息", "value": "节点执行失败"},
        ],
        error_summary="节点执行失败",
        node_path=["preprocess_subgraph", "query_plan"],
    )

    assert payload["display_input_items"] == [
        {"key": "normalized_query", "label": "规范化问题", "value": "解释 CoT 和 ToT 的区别"}
    ]
    assert payload["display_output_items"] == [
        {"key": "query_items", "label": "检索查询项", "value": ["1. [main] 解释 CoT 和 ToT 的区别"]},
        {"key": "reason", "label": "原因", "value": "保留主问题并生成完整检索项"},
        {"key": "next_node_label", "label": "下一跳", "value": "子查询派发"},
        {"key": "error_summary", "label": "错误信息", "value": "节点执行失败"},
    ]
    assert payload["error_summary"] == "节点执行失败"
    assert payload["node_path"] == ["preprocess_subgraph", "query_plan"]
    assert payload["node"] == {
        "id": "query_plan",
        "name": "query_plan",
    }


def test_build_graph_stream_options_prefers_langgraph_v2_with_tasks() -> None:
    assert KbChatService._build_graph_stream_options() == {
        "stream_mode": ["messages", "updates", "custom", "tasks"],
        "subgraphs": True,
        "version": "v2",
    }


def test_normalize_graph_stream_event_accepts_langgraph_v2_stream_part() -> None:
    normalized = KbChatService._normalize_graph_stream_event(
        {
            "type": "tasks",
            "ns": ("retrieval_subgraph:task-1", "retrieve_subquery"),
            "data": {
                "id": "task-1",
                "name": "retrieve_subquery",
                "input": {"query": "什么是 CoT"},
                "triggers": ["branch:0"],
            },
        }
    )

    assert normalized == (
        "tasks",
        {
            "id": "task-1",
            "name": "retrieve_subquery",
            "input": {"query": "什么是 CoT"},
            "triggers": ["branch:0"],
        },
        ["retrieval_subgraph:task-1", "retrieve_subquery"],
    )


def test_build_step_payload_from_task_event_maps_start_and_waiting_user() -> None:
    started = KbChatService._build_step_payload_from_task_event(
        payload={
            "id": "task-1",
            "name": "retrieve_subquery",
            "input": {"query": "什么是 CoT"},
            "triggers": ["branch:0"],
        },
        node_path=["retrieval_subgraph:task-1", "retrieve_subquery"],
    )
    waiting = KbChatService._build_step_payload_from_task_event(
        payload={
            "id": "task-1",
            "name": "ambiguity_check",
            "error": None,
            "interrupts": [{"id": "interrupt-1"}],
            "result": {},
        },
        node_path=["preprocess_subgraph:task-2", "ambiguity_check"],
    )

    assert started == {
        "execution_id": "task-1",
        "step_id": "retrieve_subquery",
        "label": "retrieve_subquery",
        "status": "started",
        "node": "retrieve_subquery",
        "ts": started["ts"],
        "meta": {
            "task_id": "task-1",
            "node_path": ["retrieval_subgraph:task-1", "retrieve_subquery"],
            "triggers": ["branch:0"],
        },
    }
    assert waiting == {
        "execution_id": "task-1",
        "step_id": "ambiguity_check",
        "label": "ambiguity_check",
        "status": "waiting_user",
        "node": "ambiguity_check",
        "ts": waiting["ts"],
        "meta": {
            "task_id": "task-1",
            "node_path": ["preprocess_subgraph:task-2", "ambiguity_check"],
            "interrupt_count": 1,
        },
    }


def test_build_step_payload_from_task_event_promotes_task_id_to_execution_id() -> None:
    started = KbChatService._build_step_payload_from_task_event(
        payload={
            "id": "task-branch-1",
            "name": "retrieve_subquery",
            "input": {"query": "什么是 CoT"},
        },
        node_path=["retrieval_subgraph:task-branch-1", "retrieve_subquery"],
    )

    assert started is not None
    assert started["execution_id"] == "task-branch-1"
    assert started["meta"]["task_id"] == "task-branch-1"


def test_build_node_io_payload_includes_execution_id_for_detail_binding() -> None:
    run_id = uuid.uuid4()

    payload = KbChatService._build_node_io_payload(
        run_id=run_id,
        execution_id="task-branch-1",
        node_name="retrieve_subquery",
        node_id="retrieve_subquery",
        phase="end",
        attempt=1,
        node_path=["retrieval_subgraph:task-branch-1", "retrieve_subquery"],
    )

    assert payload["execution_id"] == "task-branch-1"
