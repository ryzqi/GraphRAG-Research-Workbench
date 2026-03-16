from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import StreamingResponse

import app.api.v1.endpoints.chats as chats_endpoint
from app.core.errors import AppError
from app.models.chat_session import ChatSessionType
from app.schemas.chats import ChatMessageCreate


@pytest.mark.asyncio
async def test_create_chat_message_stream_primes_kb_generator_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    async def fake_events():
        started.append("started")
        yield ("meta", {"run_id": "run-1"})
        yield ("final", {"status": "succeeded"})

    class _FakeKbChatService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def answer_stream(self, **_kwargs):
            return fake_events()

    monkeypatch.setattr(chats_endpoint, "KbChatService", _FakeKbChatService)
    monkeypatch.setattr(
        chats_endpoint,
        "encode_sse",
        lambda events, **_kwargs: events,
    )

    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=ChatSessionType.KB_CHAT,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                llm_client=object(),
                milvus_client=object(),
                embedding_client=object(),
                rerank_client=object(),
                redis=object(),
            )
        )
    )

    response = await chats_endpoint.create_chat_message_stream(
        db=db,
        request=request,
        session_id=session.id,
        body=ChatMessageCreate(content="请回答问题"),
    )

    assert isinstance(response, StreamingResponse)
    assert started == ["started"]


@pytest.mark.asyncio
async def test_create_chat_message_stream_surfaces_preflight_error_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_events():
        raise AppError(
            code="CHAT_RUN_CONFLICT",
            message="当前会话已有运行中的知识库问答任务，请先完成澄清或等待结束",
            status_code=409,
        )
        yield ("meta", {"run_id": "unreachable"})

    class _FakeKbChatService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def answer_stream(self, **_kwargs):
            return fake_events()

    monkeypatch.setattr(chats_endpoint, "KbChatService", _FakeKbChatService)
    monkeypatch.setattr(
        chats_endpoint,
        "encode_sse",
        lambda events, **_kwargs: events,
    )

    session = SimpleNamespace(
        id=uuid.uuid4(),
        session_type=ChatSessionType.KB_CHAT,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=session)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                llm_client=object(),
                milvus_client=object(),
                embedding_client=object(),
                rerank_client=object(),
                redis=object(),
            )
        )
    )

    with pytest.raises(AppError) as exc_info:
        await chats_endpoint.create_chat_message_stream(
            db=db,
            request=request,
            session_id=session.id,
            body=ChatMessageCreate(content="请再次回答同一个问题。"),
        )

    assert exc_info.value.code == "CHAT_RUN_CONFLICT"
    assert exc_info.value.status_code == 409
