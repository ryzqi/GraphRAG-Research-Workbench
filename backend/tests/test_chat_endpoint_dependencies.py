from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

from app.api.v1.endpoints.chat_dependencies import (
    build_general_chat_service,
    build_kb_chat_service,
    stream_heartbeat_payload,
)
from app.integrations.llm_client import LLMClient
from app.services.general_chat_service import GeneralChatService
from app.services.kb_chat_service import KbChatService


class _DummyDb:
    pass


def _build_request() -> SimpleNamespace:
    state = SimpleNamespace(
        llm_client=cast(LLMClient, object()),
        milvus_client=object(),
        embedding_client=object(),
        rerank_client=object(),
        redis=object(),
        http_client=object(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_build_kb_chat_service_uses_request_state_dependencies() -> None:
    db = _DummyDb()
    request = _build_request()

    service = build_kb_chat_service(db=db, request=request)

    assert isinstance(service, KbChatService)
    assert service._db is db
    assert service._llm is request.app.state.llm_client
    assert service._embedding is request.app.state.embedding_client


def test_build_general_chat_service_uses_request_state_dependencies() -> None:
    db = _DummyDb()
    request = _build_request()

    service = build_general_chat_service(db=db, request=request)

    assert isinstance(service, GeneralChatService)
    assert service._db is db
    assert service._llm is request.app.state.llm_client
    assert service._redis is request.app.state.redis
    assert service._http_client is request.app.state.http_client


def test_stream_heartbeat_payload_returns_utc_iso_timestamp() -> None:
    payload = stream_heartbeat_payload()

    assert payload['type'] == 'heartbeat'
    parsed = datetime.fromisoformat(payload['ts'])
    assert parsed.tzinfo == timezone.utc
