"""研究 v2 编排与持久化服务。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, bad_request, not_found
from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseReadiness,
    KnowledgeBaseStatus,
)
from app.models.research_artifact import ResearchArtifact
from app.models.research_event import ResearchEvent
from app.models.research_session import (
    TERMINAL_RESEARCH_SESSION_STATUSES,
    ResearchSession,
    ResearchSessionStatus,
)
from app.schemas.research_v2 import (
    ResearchArtifactsRead,
    ResearchEventEnvelope,
    ResearchResumeRequest,
    ResearchSessionCreateRequest,
)
from app.worker.celery_app import celery_app


class ResearchEventStore:
    """ResearchEvent 追加写存储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        session_obj: ResearchSession,
        event_type: str,
        payload: dict,
        event_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ResearchEvent:
        resolved_event_id = event_id or str(uuid.uuid4())

        existing = await self._session.execute(
            select(ResearchEvent).where(
                ResearchEvent.session_id == session_obj.id,
                ResearchEvent.event_id == resolved_event_id,
            )
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            return found

        for _ in range(5):
            await self._session.refresh(session_obj)
            next_sequence = int(session_obj.last_event_sequence or 0) + 1
            record = ResearchEvent(
                session_id=session_obj.id,
                event_id=resolved_event_id,
                sequence=next_sequence,
                event_type=event_type,
                payload=payload,
                trace_id=trace_id or session_obj.trace_id,
                idempotency_key=idempotency_key,
            )
            session_obj.last_event_sequence = next_sequence
            self._session.add(record)
            try:
                await self._session.commit()
                await self._session.refresh(record)
                await self._session.refresh(session_obj)
                return record
            except IntegrityError:
                await self._session.rollback()
                session_obj = await self._session.get(ResearchSession, session_obj.id)  # type: ignore[assignment]
                if session_obj is None:
                    raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")

                again = await self._session.execute(
                    select(ResearchEvent).where(
                        ResearchEvent.session_id == session_obj.id,
                        ResearchEvent.event_id == resolved_event_id,
                    )
                )
                dedup = again.scalar_one_or_none()
                if dedup is not None:
                    return dedup

        raise RuntimeError("研究事件写入冲突重试失败")

    @staticmethod
    def to_envelope(event: ResearchEvent) -> ResearchEventEnvelope:
        return ResearchEventEnvelope(
            event_id=event.event_id,
            sequence=event.sequence,
            timestamp=event.created_at,
            event_type=event.event_type,
            session_id=event.session_id,
            payload=event.payload,
            trace_id=event.trace_id,
            idempotency_key=event.idempotency_key,
        )


class ResearchArtifactStore:
    """ResearchArtifact 读写封装。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_text(self, *, session_id: uuid.UUID, key: str, content: str) -> None:
        existing = await self._session.execute(
            select(ResearchArtifact).where(
                ResearchArtifact.session_id == session_id,
                ResearchArtifact.artifact_key == key,
            )
        )
        record = existing.scalar_one_or_none()
        if record is None:
            record = ResearchArtifact(
                session_id=session_id,
                artifact_key=key,
                content_text=content,
            )
            self._session.add(record)
        else:
            record.content_text = content
        await self._session.commit()

    async def upsert_json(self, *, session_id: uuid.UUID, key: str, content: dict) -> None:
        existing = await self._session.execute(
            select(ResearchArtifact).where(
                ResearchArtifact.session_id == session_id,
                ResearchArtifact.artifact_key == key,
            )
        )
        record = existing.scalar_one_or_none()
        if record is None:
            record = ResearchArtifact(
                session_id=session_id,
                artifact_key=key,
                content_json=content,
            )
            self._session.add(record)
        else:
            record.content_json = content
        await self._session.commit()

    async def get_report_artifacts(self, *, session_id: uuid.UUID) -> ResearchArtifactsRead:
        stmt = select(ResearchArtifact).where(ResearchArtifact.session_id == session_id)
        rows = list((await self._session.execute(stmt)).scalars().all())
        report_md: str | None = None
        report_json: dict | None = None
        updated_at: datetime | None = None
        for item in rows:
            if item.artifact_key == "report_md":
                report_md = item.content_text
            elif item.artifact_key == "report_json":
                report_json = item.content_json
            if updated_at is None or item.updated_at > updated_at:
                updated_at = item.updated_at
        return ResearchArtifactsRead(
            session_id=session_id,
            report_md=report_md,
            report_json=report_json,
            updated_at=updated_at,
        )


class ResearchV2Service:
    """研究 v2 编排服务。"""

    def __init__(self, celery: Celery | None = None) -> None:
        self._celery = celery or celery_app

    async def _validate_kbs(
        self, session: AsyncSession, selected_kb_ids: list[uuid.UUID]
    ) -> None:
        if not selected_kb_ids:
            raise bad_request(code="RESEARCH_MISSING_KB_IDS", message="至少选择一个知识库")
        stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(selected_kb_ids))
        kbs = list((await session.execute(stmt)).scalars().all())
        if len(kbs) != len(selected_kb_ids):
            raise bad_request(code="KB_NOT_FOUND", message="存在不存在的知识库")

        not_selectable = [
            str(kb.id)
            for kb in kbs
            if kb.status != KnowledgeBaseStatus.ACTIVE
            or kb.readiness != KnowledgeBaseReadiness.READY
        ]
        if not_selectable:
            raise bad_request(
                code="KB_NOT_SELECTABLE",
                message="所选知识库尚不可用于业务入口",
                details={"kb_ids": not_selectable},
            )

    async def create_session(
        self, session: AsyncSession, req: ResearchSessionCreateRequest
    ) -> ResearchSession:
        await self._validate_kbs(session, req.selected_kb_ids)

        trace_id = str(uuid.uuid4())
        research_session = ResearchSession(
            thread_id=str(uuid.uuid4()),
            question=req.question,
            selected_kb_ids=req.selected_kb_ids,
            allow_external=req.allow_external,
            mode=req.mode,
            status=ResearchSessionStatus.QUEUED,
            trace_id=trace_id,
        )
        session.add(research_session)
        await session.commit()
        await session.refresh(research_session)

        event_store = ResearchEventStore(session)
        await event_store.append(
            session_obj=research_session,
            event_type="session.created",
            payload={"status": research_session.status.value},
            trace_id=trace_id,
        )
        await event_store.append(
            session_obj=research_session,
            event_type="session.queued",
            payload={"status": research_session.status.value},
            trace_id=trace_id,
        )

        self._celery.send_task(
            "app.worker.tasks.research.run_research_v2",
            args=[str(research_session.id), None, None, "continue", None],
        )
        return research_session

    async def get_session(
        self, session: AsyncSession, session_id: uuid.UUID
    ) -> ResearchSession | None:
        return await session.get(ResearchSession, session_id)

    async def get_events_since(
        self,
        session: AsyncSession,
        *,
        session_id: uuid.UUID,
        last_event_id: str | None = None,
        resume_from_event_id: str | None = None,
    ) -> list[ResearchEventEnvelope]:
        start_event_id = last_event_id or resume_from_event_id
        start_sequence = 0
        if start_event_id:
            event_stmt = select(ResearchEvent).where(
                ResearchEvent.session_id == session_id,
                ResearchEvent.event_id == start_event_id,
            )
            existing = (await session.execute(event_stmt)).scalar_one_or_none()
            if existing is not None:
                start_sequence = existing.sequence

        stmt = (
            select(ResearchEvent)
            .where(
                ResearchEvent.session_id == session_id,
                ResearchEvent.sequence > start_sequence,
            )
            .order_by(ResearchEvent.sequence.asc())
        )
        rows = list((await session.execute(stmt)).scalars().all())
        return [ResearchEventStore.to_envelope(item) for item in rows]

    async def interrupt_session(
        self,
        session: AsyncSession,
        *,
        session_id: uuid.UUID,
        reason: str | None = None,
    ) -> ResearchSession:
        current = await session.get(ResearchSession, session_id)
        if current is None:
            raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")
        if current.status in TERMINAL_RESEARCH_SESSION_STATUSES:
            raise bad_request(
                code="RESEARCH_SESSION_TERMINAL",
                message="终态会话不支持中断",
            )

        current.status = ResearchSessionStatus.INTERRUPTED
        await session.commit()
        await session.refresh(current)

        event_store = ResearchEventStore(session)
        await event_store.append(
            session_obj=current,
            event_type="session.interrupted",
            payload={"reason": reason or "manual_interrupt"},
        )
        return current

    async def resume_session(
        self,
        session: AsyncSession,
        *,
        session_id: uuid.UUID,
        req: ResearchResumeRequest,
    ) -> ResearchSession:
        current = await session.get(ResearchSession, session_id)
        if current is None:
            raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")

        if (
            current.last_resume_idempotency_key
            and current.last_resume_idempotency_key == req.idempotency_key
        ):
            return current

        event_store = ResearchEventStore(session)

        if current.status in TERMINAL_RESEARCH_SESSION_STATUSES:
            await event_store.append(
                session_obj=current,
                event_type="session.resume_rejected",
                payload={"reason": "session_terminal", "status": current.status.value},
                idempotency_key=req.idempotency_key,
            )
            raise AppError(
                code="RESEARCH_SESSION_TERMINAL",
                message="终态会话不支持恢复",
                status_code=409,
            )

        if req.decision == "terminate":
            current.status = ResearchSessionStatus.CANCELED
            current.finished_at = datetime.now(timezone.utc)
            current.last_resume_idempotency_key = req.idempotency_key
            current.last_resume_response = {
                "status": current.status.value,
                "decision": req.decision,
            }
            await session.commit()
            await session.refresh(current)
            await event_store.append(
                session_obj=current,
                event_type="session.canceled",
                payload={"decision": req.decision},
                idempotency_key=req.idempotency_key,
            )
            return current

        current.status = ResearchSessionStatus.RESUMED
        current.last_resume_idempotency_key = req.idempotency_key
        current.last_resume_response = {
            "status": current.status.value,
            "decision": req.decision,
            "resume_from_event_id": req.resume_from_event_id,
        }
        await session.commit()
        await session.refresh(current)

        await event_store.append(
            session_obj=current,
            event_type="session.resumed",
            payload={
                "decision": req.decision,
                "instructions": req.instructions,
                "resume_from_event_id": req.resume_from_event_id,
            },
            idempotency_key=req.idempotency_key,
        )

        current.status = ResearchSessionStatus.RUNNING
        await session.commit()
        await session.refresh(current)
        await event_store.append(
            session_obj=current,
            event_type="session.running",
            payload={"reason": "resume"},
            idempotency_key=req.idempotency_key,
        )

        self._celery.send_task(
            "app.worker.tasks.research.run_research_v2",
            args=[
                str(current.id),
                req.resume_from_event_id,
                req.idempotency_key,
                req.decision,
                req.instructions,
            ],
        )
        return current

    async def get_artifacts(
        self, session: AsyncSession, *, session_id: uuid.UUID
    ) -> ResearchArtifactsRead:
        current = await session.get(ResearchSession, session_id)
        if current is None:
            raise not_found("研究会话不存在", code="RESEARCH_SESSION_NOT_FOUND")
        return await ResearchArtifactStore(session).get_report_artifacts(session_id=session_id)

