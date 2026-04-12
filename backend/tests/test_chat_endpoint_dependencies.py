from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from app.api.dependencies.services import (
    build_general_chat_service,
    build_kb_chat_service,
)
from app.api.v1.endpoints.chat_dependencies import stream_heartbeat_payload
from app.bootstrap.app_resources import AppResources
from app.integrations.llm_client import LLMClient
from app.services.general_chat_service import GeneralChatService
from app.services.kb_chat_service import KbChatService


class _DummyDb:
    pass


def _build_resources() -> AppResources:
    return AppResources(
        engine=object(),
        http_client=object(),
        embedding_http_client=object(),
        llm_client=cast(LLMClient, object()),
        milvus_client=object(),
        embedding_client=object(),
        rerank_client=object(),
        redis=object(),
    )


def test_build_kb_chat_service_uses_typed_app_resources() -> None:
    db = _DummyDb()
    resources = _build_resources()

    service = build_kb_chat_service(db=db, resources=resources)

    assert isinstance(service, KbChatService)
    assert service._db is db
    assert service._llm is resources.llm_client
    assert service._embedding is resources.embedding_client


def test_build_general_chat_service_uses_typed_app_resources() -> None:
    db = _DummyDb()
    resources = _build_resources()

    service = build_general_chat_service(db=db, resources=resources)

    assert isinstance(service, GeneralChatService)
    assert service._db is db
    assert service._llm is resources.llm_client
    assert service._redis is resources.redis
    assert service._http_client is resources.http_client


def test_stream_heartbeat_payload_returns_utc_iso_timestamp() -> None:
    payload = stream_heartbeat_payload()

    assert payload['type'] == 'heartbeat'
    parsed = datetime.fromisoformat(payload['ts'])
    assert parsed.tzinfo == timezone.utc
