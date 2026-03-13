from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.errors import AppError
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_session import AgentMode
from app.services.kb_chat_service import KbChatService


def _build_service() -> KbChatService:
    service = object.__new__(KbChatService)
    service._db = AsyncMock()
    return service


def _build_running_run(*, run_id: uuid.UUID | None = None) -> AgentRun:
    return AgentRun(
        id=run_id or uuid.uuid4(),
        run_type=AgentRunType.KB_ANSWER,
        question="question",
        mode=AgentMode.SINGLE_AGENT,
        status=AgentRunStatus.RUNNING,
    )


@pytest.mark.asyncio
async def test_ensure_no_running_kb_chat_run_raises_conflict() -> None:
    service = _build_service()
    running = _build_running_run()
    service._get_running_kb_chat_run = AsyncMock(return_value=running)

    with pytest.raises(AppError) as exc_info:
        await service._ensure_no_running_kb_chat_run(session_id=uuid.uuid4())

    assert exc_info.value.code == "CHAT_RUN_CONFLICT"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_ensure_kb_chat_resume_target_valid_rejects_other_running_run() -> None:
    service = _build_service()
    target_run = _build_running_run(run_id=uuid.uuid4())
    other_running = _build_running_run(run_id=uuid.uuid4())
    service._get_running_kb_chat_run = AsyncMock(return_value=other_running)

    with pytest.raises(AppError) as exc_info:
        await service._ensure_kb_chat_resume_target_valid(
            session=type("Session", (), {"id": uuid.uuid4()})(),
            run=target_run,
        )

    assert exc_info.value.code == "CHAT_RUN_CONFLICT"
    assert exc_info.value.status_code == 409
