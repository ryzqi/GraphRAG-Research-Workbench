from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock

from app.api.v1.endpoints import chats as chats_endpoint
from app.core.errors import AppError
from app.core.settings import get_settings
from app.models.knowledge_base import KnowledgeBaseReadiness, KnowledgeBaseStatus
from app.schemas.chats import ChatSessionCreate


def _ready_kb(kb_id: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=kb_id,
        status=KnowledgeBaseStatus.ACTIVE,
        readiness=KnowledgeBaseReadiness.READY,
    )


async def _refresh_stub(obj) -> None:
    now = datetime.now(timezone.utc)
    if getattr(obj, "id", None) is None:
        obj.id = uuid4()
    obj.created_at = now
    obj.updated_at = now


class _FakeDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, obj) -> None:
        await _refresh_stub(obj)


@pytest.mark.asyncio
async def test_create_chat_session_rejects_kb_config_for_general_chat() -> None:
    db = _FakeDB()
    body = ChatSessionCreate.model_validate(
        {
            "session_type": "general_chat",
            "mode": "single_agent",
            "kb_chat_config": {"rerank_enabled": False},
        }
    )

    with pytest.raises(AppError) as exc_info:
        await chats_endpoint.create_chat_session(db=db, body=body)

    assert exc_info.value.code == "CHAT_KB_CONFIG_UNSUPPORTED"


@pytest.mark.asyncio
async def test_create_chat_session_applies_default_kb_chat_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    kb_id = uuid4()
    service = SimpleNamespace(get_by_ids=AsyncMock(return_value=[_ready_kb(kb_id)]))
    monkeypatch.setattr(chats_endpoint, "KnowledgeBaseService", lambda _db: service)

    body = ChatSessionCreate.model_validate(
        {
            "session_type": "kb_chat",
            "selected_kb_ids": [str(kb_id)],
            "mode": "single_agent",
        }
    )

    result = await chats_endpoint.create_chat_session(db=db, body=body)
    settings = get_settings()

    assert result.kb_chat_config is not None
    assert result.kb_chat_config.query_rewrite_enabled == settings.retrieval_query_rewrite_enabled
    assert result.kb_chat_config.rerank_enabled == settings.retrieval_rerank_enabled
    assert result.kb_chat_config.force_retrieve_enabled == settings.kb_chat_force_retrieve


@pytest.mark.asyncio
async def test_create_chat_session_persists_custom_kb_chat_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    kb_id = uuid4()
    service = SimpleNamespace(get_by_ids=AsyncMock(return_value=[_ready_kb(kb_id)]))
    monkeypatch.setattr(chats_endpoint, "KnowledgeBaseService", lambda _db: service)

    body = ChatSessionCreate.model_validate(
        {
            "session_type": "kb_chat",
            "selected_kb_ids": [str(kb_id)],
            "mode": "single_agent",
            "kb_chat_config": {
                "query_rewrite_enabled": False,
                "multi_query_enabled": True,
                "rerank_enabled": False,
            },
        }
    )

    result = await chats_endpoint.create_chat_session(db=db, body=body)

    assert result.kb_chat_config is not None
    assert result.kb_chat_config.query_rewrite_enabled is False
    assert result.kb_chat_config.multi_query_enabled is True
    assert result.kb_chat_config.rerank_enabled is False
