from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    SemanticCacheMeta,
    resolve_kb_chat_config,
)
from app.services.kb_chat_service import KbChatService
from app.services.semantic_cache.policy import SEMANTIC_CACHE_SCHEMA_VERSION


async def _collect_events(stream) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    async for event_name, payload in stream:
        events.append((event_name, payload))
    return events


@pytest.mark.asyncio
async def test_answer_stream_cached_hit_emits_semantic_cache_step_and_node_io() -> None:
    service = KbChatService.__new__(KbChatService)
    expected_session_id = uuid.UUID("00000000-0000-0000-0000-000000000101")
    run_id = uuid.UUID("00000000-0000-0000-0000-000000000202")
    assistant_message_id = uuid.UUID("00000000-0000-0000-0000-000000000303")

    async def _ensure_no_running_kb_chat_run(*, session_id: uuid.UUID) -> None:
        assert session_id == expected_session_id

    async def _semantic_cache_lookup(**_: object) -> object:
        return object()

    async def _persist_semantic_cache_hit(**_: object) -> ChatAnswerResponse:
        return ChatAnswerResponse(
            assistant_message=ChatMessageRead(
                id=assistant_message_id,
                role="assistant",
                content="来自缓存的答案",
                created_at="2026-03-24T10:00:00Z",
            ),
            evidence=[],
            source="cached",
            cache=SemanticCacheMeta(
                hit=True,
                score=0.91,
                threshold=0.88,
                ttl_seconds=86400,
                entry_id="entry-1",
                schema_version=SEMANTIC_CACHE_SCHEMA_VERSION,
                hit_type="strong_hit",
                created_at="2026-03-24T10:00:00Z",
            ),
            stage_summaries={},
            metrics={},
            run=AgentRunRead(
                id=run_id,
                run_type="kb_answer",
                status="succeeded",
                mode="single_agent",
                question="缓存是否命中？",
                selected_kb_ids=[],
                allow_external=False,
                stage_summaries={},
                metrics={},
                created_at="2026-03-24T10:00:00Z",
                started_at="2026-03-24T10:00:00Z",
                finished_at="2026-03-24T10:00:00Z",
                error_message=None,
            ),
        )

    service._ensure_no_running_kb_chat_run = _ensure_no_running_kb_chat_run
    service._resolve_session_kb_chat_config = lambda session: resolve_kb_chat_config(raw=None)
    service._semantic_cache_lookup = _semantic_cache_lookup
    service._persist_semantic_cache_hit = _persist_semantic_cache_hit

    session = SimpleNamespace(
        id=expected_session_id,
        session_type=SimpleNamespace(value="kb_chat"),
        mode=SimpleNamespace(value="single_agent"),
    )

    events = await _collect_events(
        service.answer_stream(
            session=session,
            user_content="缓存是否命中？",
        )
    )

    assert [event_name for event_name, _ in events] == [
        "meta",
        "state",
        "step",
        "node_io",
        "stream_end",
        "state",
        "final",
    ]

    running_state = events[1][1]
    assert running_state["run_status"] == "running"
    assert running_state["current_step_id"] == "semantic_cache"
    assert running_state["current_node"] == "semantic_cache"
    assert running_state["active_path"] == ["semantic_cache"]

    step_event = events[2][1]
    assert step_event["execution_id"] == f"semantic-cache:{run_id}"
    assert step_event["step_id"] == "semantic_cache"
    assert step_event["node"] == {
        "id": "semantic_cache",
        "name": "semantic_cache",
    }
    assert step_event["status"] == "started"
    assert step_event["node_path"] == ["semantic_cache"]

    node_io_event = events[3][1]
    assert node_io_event["execution_id"] == f"semantic-cache:{run_id}"
    assert node_io_event["node_name"] == "semantic_cache"
    assert node_io_event["node_id"] == "semantic_cache"
    assert node_io_event["phase"] == "end"
    assert node_io_event["node_path"] == ["semantic_cache"]
    assert node_io_event["display_output_items"] == [
        {"key": "hit_type", "label": "命中类型", "value": "strong_hit"},
        {"key": "score", "label": "命中分数", "value": "0.91"},
        {"key": "threshold", "label": "阈值", "value": "0.88"},
        {"key": "ttl_seconds", "label": "TTL", "value": "86400"},
    ]

    succeeded_state = events[5][1]
    assert succeeded_state["run_status"] == "succeeded"
    assert succeeded_state["current_step_id"] == "semantic_cache"
    assert succeeded_state["current_node"] == "semantic_cache"
    assert succeeded_state["active_path"] == ["semantic_cache"]

    final_event = events[6][1]
    assert final_event["source"] == "cached"
    assert final_event["cache"] == {
        "hit": True,
        "score": 0.91,
        "threshold": 0.88,
        "ttl_seconds": 86400,
        "entry_id": "entry-1",
        "schema_version": SEMANTIC_CACHE_SCHEMA_VERSION,
        "hit_type": "strong_hit",
        "created_at": "2026-03-24T10:00:00Z",
    }
