"""Research event append-only store。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession


class ResearchEventStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._event_id_index: dict[tuple[uuid.UUID, str], ResearchEvent] = {}
        self._idempotency_index: dict[tuple[uuid.UUID, str], ResearchEvent] = {}
        self._indexed_session_ids: set[uuid.UUID] = set()

    @staticmethod
    def _require_session_id(session: ResearchSession) -> uuid.UUID:
        if session.id is None:
            raise ValueError("research session id is required")
        return session.id

    def _index_session_events(self, session: ResearchSession) -> None:
        session_id = self._require_session_id(session)
        if session_id in self._indexed_session_ids:
            return
        loaded_events = session.__dict__.get("events")
        if isinstance(loaded_events, list):
            for item in loaded_events:
                self._event_id_index[(session_id, item.event_id)] = item
                if item.idempotency_key is not None:
                    self._idempotency_index[
                        (session_id, item.idempotency_key)
                    ] = item
        self._indexed_session_ids.add(session_id)

    def _cache_event(
        self,
        *,
        session: ResearchSession,
        event: ResearchEvent,
    ) -> ResearchEvent:
        session_id = self._require_session_id(session)
        self._event_id_index[(session_id, event.event_id)] = event
        if event.idempotency_key is not None:
            self._idempotency_index[(session_id, event.idempotency_key)] = event
        loaded_events = session.__dict__.get("events")
        if isinstance(loaded_events, list) and not any(
            item.event_id == event.event_id for item in loaded_events
        ):
            loaded_events.append(event)
        session.last_event_sequence = max(
            int(session.last_event_sequence or 0),
            int(event.sequence or 0),
        )
        return event

    def _cached_existing_event(
        self,
        *,
        session: ResearchSession,
        event_id: str | None,
        idempotency_key: str | None,
    ) -> ResearchEvent | None:
        session_id = self._require_session_id(session)
        self._index_session_events(session)
        if event_id is not None:
            existing = self._event_id_index.get((session_id, event_id))
            if existing is not None:
                return existing
        if idempotency_key is not None:
            return self._idempotency_index.get((session_id, idempotency_key))
        return None

    async def _load_existing_event(
        self,
        *,
        session: ResearchSession,
        event_id: str | None,
        idempotency_key: str | None,
    ) -> ResearchEvent | None:
        session_id = self._require_session_id(session)
        if event_id is not None:
            existing = (
                await self._db.execute(
                    select(ResearchEvent).where(
                        ResearchEvent.session_id == session_id,
                        ResearchEvent.event_id == event_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._cache_event(session=session, event=existing)
        if idempotency_key is not None:
            existing = (
                await self._db.execute(
                    select(ResearchEvent).where(
                        ResearchEvent.session_id == session_id,
                        ResearchEvent.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._cache_event(session=session, event=existing)
        return None

    async def _lock_last_event_sequence(self, session_id: uuid.UUID) -> int:
        current_sequence = (
            await self._db.execute(
                select(ResearchSession.last_event_sequence)
                .where(ResearchSession.id == session_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if current_sequence is None:
            raise ValueError(f"research session not found: {session_id}")
        return int(current_sequence or 0)

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
        existing = self._cached_existing_event(
            session=session,
            event_id=event_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing

        session_id = self._require_session_id(session)
        current_sequence = await self._lock_last_event_sequence(session_id)
        existing = await self._load_existing_event(
            session=session,
            event_id=event_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return existing

        sequence_next = current_sequence + 1
        resolved_event_id = event_id or f"evt-{sequence_next:06d}-{uuid.uuid4().hex[:8]}"
        inserted_row = (
            await self._db.execute(
                pg_insert(ResearchEvent)
                .values(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    event_id=resolved_event_id,
                    sequence=sequence_next,
                    event_type=event_type,
                    phase=phase,
                    namespace=namespace,
                    payload=payload,
                    trace_id=trace_id,
                    idempotency_key=idempotency_key,
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing()
                .returning(ResearchEvent.id)
            )
        ).scalar_one_or_none()
        if inserted_row is None:
            existing = await self._load_existing_event(
                session=session,
                event_id=event_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                return existing
            raise RuntimeError("research event insert conflicted without resolvable key")

        session.last_event_sequence = sequence_next
        event = await self._db.get(ResearchEvent, inserted_row)
        if event is None:  # pragma: no cover - defensive guard
            raise RuntimeError("inserted research event could not be reloaded")
        return self._cache_event(session=session, event=event)
