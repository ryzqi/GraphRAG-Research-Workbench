"""Research event append-only store。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession


class ResearchEventStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def append(
        self,
        *,
        session: ResearchSession,
        event_id: str | None = None,
        event_type: str,
        phase: str,
        payload: dict[str, Any],
        namespace: str = "main",
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResearchEvent:
        existing = None
        if event_id is not None:
            existing = next(
                (item for item in session.events if item.event_id == event_id),
                None,
            )
        if existing is None and idempotency_key is not None:
            existing = next(
                (
                    item
                    for item in session.events
                    if item.idempotency_key == idempotency_key
                ),
                None,
            )
        if existing is not None:
            return existing

        session.last_event_sequence = int(session.last_event_sequence or 0) + 1
        event = ResearchEvent(
            session=session,
            event_id=event_id
            or f"evt-{session.last_event_sequence:06d}-{uuid.uuid4().hex[:8]}",
            sequence=session.last_event_sequence,
            event_type=event_type,
            phase=phase,
            namespace=namespace,
            payload=payload,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc),
        )
        self._db.add(event)
        return event
