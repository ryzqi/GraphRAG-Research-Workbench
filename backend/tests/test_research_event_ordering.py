from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import builtins
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.repositories.research_session_repository import ResearchSessionRepository
from app.services.research_service import ResearchService


@asynccontextmanager
async def _isolated_research_db() -> AsyncIterator[async_sessionmaker]:
    settings = get_settings()
    schema = f"test_research_order_{uuid.uuid4().hex[:8]}"
    base_engine = create_async_engine(settings.database_url)
    test_engine = create_async_engine(
        settings.database_url,
        connect_args={
            "server_settings": {
                "search_path": f"{schema},public",
            }
        },
    )
    try:
        async with base_engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(sa.text(f'SET search_path TO "{schema}", public'))
            await conn.run_sync(
                lambda sync_conn: ResearchSession.__table__.create(sync_conn)
            )
            await conn.run_sync(
                lambda sync_conn: ResearchEvent.__table__.create(sync_conn)
            )
    except sa.exc.OperationalError as exc:  # pragma: no cover - environment guard
        await test_engine.dispose()
        await base_engine.dispose()
        pytest.skip(f"Postgres unavailable: {exc}")

    try:
        yield async_sessionmaker(test_engine, expire_on_commit=False)
    finally:
        await test_engine.dispose()
        async with base_engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await base_engine.dispose()


def test_build_effective_planning_question_uses_relationship_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="原始问题",
        status=ResearchSessionStatus.CLARIFYING,
    )
    session.events = [
        ResearchEvent(
            session_id=session.id,
            event_id="evt-000001",
            sequence=1,
            event_type="research.clarification.requested",
            phase="planner",
            namespace="main",
            payload={
                "summary": "先确认时间范围",
                "questions": [
                    {
                        "id": "q1",
                        "question": "你关心哪个时间段？",
                        "why_it_matters": "决定检索窗口",
                    }
                ],
            },
            created_at=datetime.now(timezone.utc),
        ),
        ResearchEvent(
            session_id=session.id,
            event_id="evt-000002",
            sequence=2,
            event_type="research.clarification.submitted",
            phase="planner",
            namespace="main",
            payload={"answer": "关注 2025 年之后"},
            created_at=datetime.now(timezone.utc),
        ),
        ResearchEvent(
            session_id=session.id,
            event_id="evt-000003",
            sequence=3,
            event_type="research.clarification.requested",
            phase="planner",
            namespace="main",
            payload={
                "summary": "再确认目标受众",
                "questions": [
                    {
                        "id": "q2",
                        "question": "报告给谁看？",
                        "why_it_matters": "影响写作深度",
                    }
                ],
            },
            created_at=datetime.now(timezone.utc),
        ),
    ]

    original_sorted = builtins.sorted

    def _raising_sorted(iterable, *args, **kwargs):  # noqa: ANN001, ANN202
        if iterable is session.events:
            raise AssertionError("不应再对 session.events 调用 sorted")
        return original_sorted(iterable, *args, **kwargs)

    monkeypatch.setattr(builtins, "sorted", _raising_sorted)

    result = ResearchService._build_effective_planning_question(
        session=session,
        answer="补充：受众是技术负责人",
    )

    assert result.index("先确认时间范围") < result.index("再确认目标受众")
    assert result.index("关注 2025 年之后") < result.index("补充：受众是技术负责人")


@pytest.mark.asyncio
async def test_research_session_repository_orders_events_by_sequence() -> None:
    async with _isolated_research_db() as sessionmaker:
        session_id = uuid.uuid4()
        async with sessionmaker() as db:
            session = ResearchSession(
                id=session_id,
                thread_id="thread-1",
                question="研究问题",
                status=ResearchSessionStatus.RUNNING,
            )
            db.add(session)
            db.add_all(
                [
                    ResearchEvent(
                        session_id=session_id,
                        event_id="evt-000003",
                        sequence=3,
                        event_type="research.runtime.activity",
                        phase="runtime",
                        namespace="main",
                        payload={"step": 3},
                        created_at=datetime.now(timezone.utc),
                    ),
                    ResearchEvent(
                        session_id=session_id,
                        event_id="evt-000001",
                        sequence=1,
                        event_type="research.run.started",
                        phase="runtime",
                        namespace="main",
                        payload={"step": 1},
                        created_at=datetime.now(timezone.utc),
                    ),
                    ResearchEvent(
                        session_id=session_id,
                        event_id="evt-000002",
                        sequence=2,
                        event_type="research.plan_progress.updated",
                        phase="runtime",
                        namespace="main",
                        payload={"step": 2},
                        created_at=datetime.now(timezone.utc),
                    ),
                ]
            )
            await db.commit()

        async with sessionmaker() as db:
            repository = ResearchSessionRepository(db)
            loaded = await repository.get_with_details(session_id)

        assert loaded is not None
        assert [event.sequence for event in loaded.events] == [1, 2, 3]
