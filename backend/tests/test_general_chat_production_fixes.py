from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import ProgrammingError

from app.api.v1.endpoints.chats import router
from app.schemas.chats import ChatMessageCreate
from app.services.general_chat_service import GeneralChatService


def test_chat_message_create_supports_client_request_id() -> None:
    payload = ChatMessageCreate.model_validate(
        {
            "content": "hello",
            "client_request_id": "req_abc_123",
        }
    )
    assert payload.client_request_id == "req_abc_123"


def test_chat_message_create_rejects_blank_client_request_id() -> None:
    try:
        ChatMessageCreate.model_validate(
            {
                "content": "hello",
                "client_request_id": "   ",
            }
        )
    except Exception:
        return
    raise AssertionError("Expected blank client_request_id to be rejected")


def test_chats_router_exposes_pending_general_run_endpoint() -> None:
    route_paths = {route.path for route in router.routes}
    assert "/{session_id}/runs/pending-general" in route_paths


def test_chat_request_dedup_model_exists() -> None:
    from app.models.chat_request_dedup import ChatRequestDedup

    assert ChatRequestDedup.__tablename__ == "chat_request_dedup"


def test_detects_missing_dedup_table_error() -> None:
    exc = ProgrammingError(
        "SELECT * FROM chat_request_dedup",
        {},
        Exception('relation "chat_request_dedup" does not exist'),
    )
    assert GeneralChatService._is_missing_dedup_table_error(exc)


def test_ignores_non_dedup_programming_error() -> None:
    exc = ProgrammingError(
        "SELECT * FROM chat_sessions",
        {},
        Exception('relation "chat_sessions" does not exist'),
    )
    assert not GeneralChatService._is_missing_dedup_table_error(exc)


@pytest.mark.asyncio
async def test_claim_request_dedup_skips_when_table_missing() -> None:
    service = object.__new__(GeneralChatService)
    db = AsyncMock()
    db.execute.side_effect = ProgrammingError(
        "SELECT * FROM chat_request_dedup",
        {},
        Exception('relation "chat_request_dedup" does not exist'),
    )
    service._db = db
    service._dedup_missing_table_warned = False

    dedup, claimed = await service._claim_request_dedup(
        session_id=uuid.uuid4(),
        client_request_id="req-001",
    )

    assert dedup is None
    assert claimed is True
    db.rollback.assert_awaited_once()
