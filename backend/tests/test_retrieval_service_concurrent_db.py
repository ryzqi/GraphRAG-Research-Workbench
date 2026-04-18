"""回归：验证 RetrievalService._db_execute 允许并发。"""

import asyncio
from unittest.mock import MagicMock

import pytest

from app.services.retrieval_service import RetrievalService


class _ParallelProbe:
    def __init__(self) -> None:
        self.in_flight = 0
        self.peak_parallel = 0


class _FakeSession:
    def __init__(self, probe: _ParallelProbe) -> None:
        self.execute_calls: list[object] = []
        self._probe = probe

    async def execute(self, stmt: object) -> MagicMock:
        self.execute_calls.append(stmt)
        self._probe.in_flight += 1
        self._probe.peak_parallel = max(
            self._probe.peak_parallel,
            self._probe.in_flight,
        )
        await asyncio.sleep(0.01)
        self._probe.in_flight -= 1
        return MagicMock(name="Result")

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSessionmaker:
    def __init__(self) -> None:
        self.probe = _ParallelProbe()
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession(self.probe)
        self.sessions.append(session)
        return session


async def test_db_execute_runs_queries_in_parallel_branches() -> None:
    sm = _FakeSessionmaker()
    service = RetrievalService(
        sessionmaker=sm,
        milvus=MagicMock(),
        embedding=MagicMock(),
    )

    async def one_branch(stmt_id: int) -> object:
        return await service._db_execute(f"stmt_{stmt_id}")

    await asyncio.gather(*(one_branch(i) for i in range(10)))

    assert len(sm.sessions) == 10, "每次 _db_execute 应该打开独立 session"
    assert all(len(session.execute_calls) == 1 for session in sm.sessions)
    assert sm.probe.peak_parallel > 1, "并发分支不应被串行锁退化"


async def test_db_execute_raises_when_sessionmaker_missing() -> None:
    service = RetrievalService(
        sessionmaker=None,
        milvus=MagicMock(),
        embedding=MagicMock(),
    )

    with pytest.raises(RuntimeError, match="db_not_configured"):
        await service._db_execute("stmt")
