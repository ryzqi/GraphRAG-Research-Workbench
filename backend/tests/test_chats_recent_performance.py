from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.endpoints import chats as chats_endpoint
from app.core.settings import get_settings
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import AgentMode, ChatSession, ChatSessionType

_RECENT_QUERY_SQL = """
EXPLAIN ANALYZE
SELECT
    cs.id,
    lm.last_message_at,
    lum.content
FROM chat_sessions cs
JOIN (
    SELECT
        session_id,
        MAX(created_at) AS last_message_at
    FROM chat_messages
    WHERE role IN ('user', 'assistant')
    GROUP BY session_id
) lm
    ON lm.session_id = cs.id
LEFT JOIN (
    SELECT
        session_id,
        content,
        ROW_NUMBER() OVER (
            PARTITION BY session_id
            ORDER BY created_at DESC
        ) AS rn
    FROM chat_messages
    WHERE role = 'user'
) lum
    ON lum.session_id = cs.id
   AND lum.rn = 1
ORDER BY lm.last_message_at DESC
LIMIT :limit
"""


def _parse_execution_time(explain_rows: list[str]) -> float:
    for row in explain_rows:
        if not row.startswith("Execution Time:"):
            continue
        value = row.split(":", 1)[1].strip()
        return float(value.removesuffix(" ms"))
    raise AssertionError("EXPLAIN ANALYZE 输出缺少 Execution Time")


@asynccontextmanager
async def _isolated_chats_db() -> AsyncIterator[async_sessionmaker]:
    settings = get_settings()
    schema = f"test_chats_recent_{uuid.uuid4().hex[:8]}"
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
                lambda sync_conn: ChatSession.__table__.create(sync_conn)
            )
            await conn.run_sync(
                lambda sync_conn: ChatMessage.__table__.create(sync_conn)
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


async def _seed_chat_sessions(
    sessionmaker: async_sessionmaker,
    *,
    session_count: int,
    messages_per_session: int,
) -> list[tuple[uuid.UUID, str, datetime]]:
    expected: list[tuple[uuid.UUID, str, datetime]] = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with sessionmaker() as db:
        sessions: list[ChatSession] = []
        for idx in range(session_count):
            session = ChatSession(
                id=uuid.uuid4(),
                session_type=ChatSessionType.GENERAL_CHAT,
                allow_external=False,
                mode=AgentMode.SINGLE_AGENT,
            )
            sessions.append(session)
            db.add(session)
        await db.flush()

        for idx, session in enumerate(sessions):
            last_user_content = ""
            last_message_at = base_time
            for msg_idx in range(messages_per_session):
                created_at = base_time + timedelta(
                    seconds=idx * messages_per_session + msg_idx
                )
                role = (
                    MessageRole.USER if msg_idx % 2 == 0 else MessageRole.ASSISTANT
                )
                content = f"session-{idx}-message-{msg_idx}"
                db.add(
                    ChatMessage(
                        session_id=session.id,
                        role=role,
                        content=content,
                        created_at=created_at,
                    )
                )
                last_message_at = created_at
                if role == MessageRole.USER:
                    last_user_content = content
            expected.append((session.id, last_user_content, last_message_at))

        await db.commit()
    return expected


@pytest.mark.asyncio
async def test_chat_messages_has_recent_query_composite_index() -> None:
    async with _isolated_chats_db() as sessionmaker:
        async with sessionmaker() as db:
            rows = (
                await db.execute(
                    sa.text(
                        """
                        SELECT indexdef
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'chat_messages'
                        ORDER BY indexname
                        """
                    )
                )
            ).scalars().all()

        assert any(
            "session_id" in row
            and "created_at DESC" in row
            and "role" in row
            for row in rows
        )


@pytest.mark.asyncio
async def test_list_recent_chats_returns_correct_rows_under_50ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _isolated_chats_db() as sessionmaker:
        expected = await _seed_chat_sessions(
            sessionmaker,
            session_count=50,
            messages_per_session=100,
        )
        
        async def _fake_get_web_search_status(**_kwargs):
            return {
                "configured": False,
                "verified": False,
                "mode": "down",
                "providers": [],
            }

        monkeypatch.setattr(
            chats_endpoint,
            "get_web_search_status",
            _fake_get_web_search_status,
        )

        async with sessionmaker() as db:
            response = await chats_endpoint.list_recent_chats(
                db=db,
                resources=SimpleNamespace(http_client=None),
                limit=20,
            )
            explain_rows = (
                await db.execute(sa.text(_RECENT_QUERY_SQL), {"limit": 20})
            ).scalars().all()

        expected_recent = list(reversed(expected))[:20]
        assert [item.id for item in response.items] == [
            item[0] for item in expected_recent
        ]
        assert [item.title for item in response.items] == [
            item[1][:30] for item in expected_recent
        ]
        assert [item.updated_at for item in response.items] == [
            item[2] for item in expected_recent
        ]
        assert _parse_execution_time(explain_rows) < 50.0
