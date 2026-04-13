from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import PendingRollbackError

from app.models.agent_run import AgentRun
from app.models.agent_run import AgentRunStatus
from app.services import general_chat_service_dedup as general_dedup


class _DirtySession:
    def __init__(self, *, persisted_run) -> None:
        self._persisted_run = persisted_run
        self.commit_calls = 0
        self.rollback_calls = 0
        self.get_calls: list[tuple[object, object]] = []

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.rollback_calls == 0:
            raise PendingRollbackError("transaction is in failed state")

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def get(self, model, identity):
        self.get_calls.append((model, identity))
        return self._persisted_run


@pytest.mark.asyncio
async def test_persist_failed_run_rolls_back_dirty_transaction_before_commit() -> None:
    run_id = uuid4()
    persisted_run = SimpleNamespace(
        id=run_id,
        status=AgentRunStatus.RUNNING,
        finished_at=None,
        error_message=None,
    )
    service = SimpleNamespace(_db=_DirtySession(persisted_run=persisted_run))

    await general_dedup._persist_failed_run(
        service,
        run=SimpleNamespace(id=run_id),
        error=RuntimeError("boom"),
    )

    assert service._db.rollback_calls == 1
    assert service._db.get_calls == [(AgentRun, run_id)]
    assert service._db.commit_calls == 1
    assert persisted_run.status == AgentRunStatus.FAILED
    assert persisted_run.error_message == "boom"
    assert persisted_run.finished_at is not None


@pytest.mark.asyncio
async def test_persist_failed_run_skips_missing_row_after_rollback() -> None:
    run_id = uuid4()
    service = SimpleNamespace(_db=_DirtySession(persisted_run=None))

    await general_dedup._persist_failed_run(
        service,
        run=SimpleNamespace(id=run_id),
        error=RuntimeError("boom"),
    )

    assert service._db.rollback_calls == 1
    assert service._db.get_calls == [(AgentRun, run_id)]
    assert service._db.commit_calls == 0
