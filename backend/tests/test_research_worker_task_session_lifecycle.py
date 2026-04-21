from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.research_session import ResearchSessionStatus
from app.worker.tasks import research as research_tasks


class _TestBase(DeclarativeBase):
    pass


class _WorkerSessionLike(_TestBase):
    __tablename__ = "test_worker_session_like"

    id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    status: Mapped[ResearchSessionStatus] = mapped_column(
        sa.Enum(ResearchSessionStatus, native_enum=False),
        nullable=False,
    )
    runtime_phase: Mapped[str | None] = mapped_column(sa.String, nullable=True)


@dataclass(slots=True)
class _WorkerCallRecord:
    execute_call_count: int = 0
    execute_detached_flags: list[bool] = field(default_factory=list)
    fail_call_count: int = 0
    fail_phases: list[str] = field(default_factory=list)
    fail_errors: list[str] = field(default_factory=list)


class _WorkerLifecycleService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        model: type[_WorkerSessionLike],
        record: _WorkerCallRecord,
    ) -> None:
        self._db = db
        self._model = model
        self._record = record

    async def get_session(self, session_id: uuid.UUID) -> _WorkerSessionLike:
        session = await self._db.get(self._model, str(session_id))
        if session is None:
            raise RuntimeError(f"missing research session: {session_id}")
        return session

    def read_plan_snapshot(self, session: _WorkerSessionLike) -> dict[str, object]:
        del session
        return {"plan": "ok"}

    async def execute_session(
        self,
        *,
        session: _WorkerSessionLike,
        plan_snapshot: dict[str, object],
    ) -> None:
        del plan_snapshot
        self._record.execute_call_count += 1
        detached = sa.inspect(session).detached
        self._record.execute_detached_flags.append(detached)
        if detached:
            raise RuntimeError("detached research session reached execute_session")

    async def fail_session(
        self,
        *,
        session: _WorkerSessionLike,
        exc: Exception,
        phase: str,
    ) -> None:
        del session
        self._record.fail_call_count += 1
        self._record.fail_phases.append(phase)
        self._record.fail_errors.append(str(exc))


@pytest.mark.asyncio
async def test_run_research_session_reloads_session_inside_live_db_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    session_id = str(uuid.uuid4())
    async with sessionmaker() as setup_db:
        setup_db.add(
            _WorkerSessionLike(
                id=session_id,
                status=ResearchSessionStatus.QUEUED,
            )
        )
        await setup_db.commit()

    record = _WorkerCallRecord()

    @asynccontextmanager
    async def _fake_managed_task_resources(*args, **kwargs):
        del args, kwargs
        yield SimpleNamespace(sessionmaker=sessionmaker)

    async def _fake_get_cached_runner(*, settings: object) -> object:
        del settings
        return object()

    def _fake_build_research_service(
        *,
        db: AsyncSession,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        runtime_runner: object | None = None,
    ) -> _WorkerLifecycleService:
        del sessionmaker, runtime_runner
        return _WorkerLifecycleService(
            db=db,
            model=_WorkerSessionLike,
            record=record,
        )

    monkeypatch.setattr(research_tasks, "get_settings", lambda: object())
    monkeypatch.setattr(
        research_tasks,
        "managed_task_resources",
        _fake_managed_task_resources,
    )
    monkeypatch.setattr(research_tasks, "get_cached_runner", _fake_get_cached_runner)
    monkeypatch.setattr(
        research_tasks,
        "build_research_service",
        _fake_build_research_service,
    )

    await research_tasks._run_research_session(session_id)

    assert record.execute_call_count == 1
    assert record.execute_detached_flags == [False]
    assert record.fail_call_count == 0
    assert record.fail_phases == []
    assert record.fail_errors == []

    await engine.dispose()
