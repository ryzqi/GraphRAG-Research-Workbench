from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.services.research_service import ResearchService


class _TestBase(DeclarativeBase):
    pass


class _StageSessionLike(_TestBase):
    __tablename__ = "test_stage_session_like"

    id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    status: Mapped[str] = mapped_column(sa.String, nullable=False)
    planner_phase: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    runtime_phase: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    finalizer_phase: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    last_event_sequence: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    metrics: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
    events: Mapped[list["_StageEventLike"]] = relationship(
        back_populates="session",
        order_by="_StageEventLike.sequence",
        cascade="all, delete-orphan",
    )


class _StageEventLike(_TestBase):
    __tablename__ = "test_stage_event_like"

    id: Mapped[str] = mapped_column(sa.String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        sa.String,
        sa.ForeignKey("test_stage_session_like.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String, nullable=False)

    session: Mapped[_StageSessionLike] = relationship(back_populates="events")


class _MinimalResearchService(ResearchService):
    def __init__(
        self,
        *,
        db: AsyncSession,
        sessionmaker: async_sessionmaker[AsyncSession],
        model: type[_StageSessionLike],
    ) -> None:
        self._db = db
        self._sessionmaker = sessionmaker
        self._model = model

    def _build_db_bound_service(self, db: AsyncSession) -> "_MinimalResearchService":
        return _MinimalResearchService(
            db=db,
            sessionmaker=self._sessionmaker,
            model=self._model,
        )

    async def get_session(self, session_id: str) -> _StageSessionLike:
        session = await self._db.get(self._model, session_id)
        if session is None:
            raise RuntimeError(f"missing stage session: {session_id}")
        return session


@pytest.mark.asyncio
async def test_run_stage_operation_syncs_snapshot_without_triggering_missing_greenlet() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    session_id = str(uuid.uuid4())
    async with sessionmaker() as setup_db:
        setup_db.add(_StageSessionLike(id=session_id, status="queued"))
        await setup_db.commit()

    async with sessionmaker() as outer_db:
        service = _MinimalResearchService(
            db=outer_db,
            sessionmaker=sessionmaker,
            model=_StageSessionLike,
        )
        session = await service.get_session(session_id)
        await outer_db.refresh(session, attribute_names=["events"])

        async def _write(
            stage_service: _MinimalResearchService,
            stage_session: _StageSessionLike,
        ) -> None:
            del stage_service
            stage_session.status = "running"
            stage_session.runtime_phase = "runtime"
            stage_session.started_at = datetime.now(timezone.utc)

        await service._run_stage_operation(
            session=session,
            state_fields=("status", "runtime_phase", "started_at"),
            operation=_write,
        )

        assert session.status == "running"
        assert session.runtime_phase == "runtime"
        assert session.started_at is not None
        assert session.updated_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_stage_operation_syncs_relationships_without_cross_session_attach_error() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    session_id = str(uuid.uuid4())
    async with sessionmaker() as setup_db:
        setup_db.add(_StageSessionLike(id=session_id, status="queued"))
        await setup_db.commit()

    async with sessionmaker() as outer_db:
        service = _MinimalResearchService(
            db=outer_db,
            sessionmaker=sessionmaker,
            model=_StageSessionLike,
        )
        session = await service.get_session(session_id)
        await outer_db.refresh(session, attribute_names=["events"])

        async def _write(
            stage_service: _MinimalResearchService,
            stage_session: _StageSessionLike,
        ) -> None:
            await stage_service._db.refresh(stage_session, attribute_names=["events"])
            stage_session.events.append(
                _StageEventLike(
                    id=str(uuid.uuid4()),
                    sequence=1,
                    event_type="research.run.failed",
                )
            )

        await service._run_stage_operation(session=session, operation=_write)

        assert "events" in session.__dict__
        assert len(session.events) == 1
        assert session.events[0].event_type == "research.run.failed"
        assert session.events[0].sequence == 1

    await engine.dispose()
