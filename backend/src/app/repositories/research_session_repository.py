from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.research_session import ResearchSession
from app.models.research_task_outbox import ResearchTaskOutbox


class ResearchSessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_with_details(self, session_id: uuid.UUID) -> ResearchSession | None:
        stmt = (
            select(ResearchSession)
            .where(ResearchSession.id == session_id)
            .options(
                selectinload(ResearchSession.artifacts),
                selectinload(ResearchSession.events),
                selectinload(ResearchSession.task_outbox_entries),
            )
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    def add(self, session: ResearchSession) -> None:
        self._db.add(session)

    def add_task_outbox_entry(self, entry: ResearchTaskOutbox) -> None:
        self._db.add(entry)

    async def flush(self) -> None:
        await self._db.flush()
