from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.settings import get_settings
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.repositories.research_session_repository import ResearchSessionRepository
from app.services.research_event_store import ResearchEventStore


@asynccontextmanager
async def _isolated_research_event_db() -> AsyncIterator[
    async_sessionmaker
]:
    settings = get_settings()
    schema = f"test_research_event_store_{uuid.uuid4().hex[:8]}"
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


@pytest.mark.asyncio
async def test_research_event_store_append_is_idempotent_under_concurrency() -> None:
    async with _isolated_research_event_db() as sessionmaker:
        session_id = uuid.uuid4()
        async with sessionmaker() as setup_db:
            setup_db.add(
                ResearchSession(
                    id=session_id,
                    thread_id=f"thread-{uuid.uuid4()}",
                    question="研究事件并发幂等测试",
                    status=ResearchSessionStatus.RUNNING,
                )
            )
            await setup_db.commit()

        barrier = asyncio.Barrier(5)

        async def _append_once() -> str:
            async with sessionmaker() as db:
                session = await ResearchSessionRepository(db).get_with_details(
                    session_id
                )
                assert session is not None
                store = ResearchEventStore(db)
                await barrier.wait()
                event = await store.append(
                    session=session,
                    event_type="research.runtime.activity",
                    phase="runtime",
                    payload={"source": "concurrency-test"},
                    idempotency_key="same-idempotency-key",
                )
                await db.commit()
                return event.event_id

        event_ids = await asyncio.gather(*[_append_once() for _ in range(5)])

        async with sessionmaker() as verify_db:
            events = list(
                (
                    await verify_db.execute(
                        sa.select(ResearchEvent).where(
                            ResearchEvent.session_id == session_id
                        )
                    )
                ).scalars()
            )
            session = await verify_db.get(ResearchSession, session_id)

        assert len(events) == 1
        assert len(set(event_ids)) == 1
        assert session is not None
        assert session.last_event_sequence == 1
