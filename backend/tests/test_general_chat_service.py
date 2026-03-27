from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Callable

import httpx
import openai
import pytest
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import AppError
from app.models.agent_run import AgentRunStatus
from app.services.general_chat_service import GeneralChatService


class _CommitRaisesStaleDataError:
    def __init__(self, *, after_rollback: Callable[[], None] | None = None) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0
        self._after_rollback = after_rollback

    async def commit(self) -> None:
        self.commit_calls += 1
        raise StaleDataError('row disappeared')

    async def rollback(self) -> None:
        self.rollback_calls += 1
        if callable(self._after_rollback):
            self._after_rollback()


class _RunIdRaisesAfterRollback:
    def __init__(self) -> None:
        self._id = uuid.uuid4()
        self._raise_on_id = False
        self.status = AgentRunStatus.RUNNING
        self.finished_at = None
        self.error_message = None

    @property
    def id(self) -> uuid.UUID:
        if self._raise_on_id:
            raise AssertionError("rollback 后不应再次访问 run.id")
        return self._id


@pytest.mark.asyncio
async def test_persist_failed_run_tolerates_stale_agent_run_row() -> None:
    service = GeneralChatService.__new__(GeneralChatService)
    service._db = _CommitRaisesStaleDataError()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        status=AgentRunStatus.RUNNING,
        finished_at=None,
        error_message=None,
    )

    await service._persist_failed_run(run=run, error=RuntimeError('glm5 failed'))

    assert service._db.commit_calls == 1
    assert service._db.rollback_calls == 1
    assert run.status == AgentRunStatus.FAILED
    assert run.error_message == 'glm5 failed'
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_persist_failed_run_does_not_access_expired_run_id_after_rollback() -> None:
    service = GeneralChatService.__new__(GeneralChatService)
    run = _RunIdRaisesAfterRollback()
    service._db = _CommitRaisesStaleDataError(
        after_rollback=lambda: setattr(run, "_raise_on_id", True)
    )

    await service._persist_failed_run(run=run, error=RuntimeError("minimax timeout"))

    assert service._db.commit_calls == 1
    assert service._db.rollback_calls == 1
    assert run.status == AgentRunStatus.FAILED
    assert run.error_message == "minimax timeout"
    assert run.finished_at is not None


def test_map_llm_exception_maps_openai_timeout_error() -> None:
    exc = openai.APITimeoutError(
        request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    )

    mapped = GeneralChatService._map_llm_exception(exc)

    assert isinstance(mapped, AppError)
    assert mapped.code == "LLM_UPSTREAM_TIMEOUT"
    assert mapped.status_code == 504
    assert mapped.details == {"exc_type": "APITimeoutError"}
