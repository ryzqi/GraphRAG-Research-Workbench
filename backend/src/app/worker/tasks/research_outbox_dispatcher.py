"""从事务 outbox 分发 research 会话任务。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.settings import get_settings
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.models.research_task_outbox import (
    ResearchTaskOutbox,
    ResearchTaskOutboxStatus,
)
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources

logger = logging.getLogger(__name__)

DEFAULT_DISPATCH_BATCH_SIZE = 50
MAX_RETRY_BACKOFF_SECONDS = 600
RETRY_BASE_SECONDS = 5
MAX_ERROR_MESSAGE_LENGTH = 2000
STALE_DISPATCHED_SECONDS = 60 * 60
STALE_RECOVERY_MESSAGE = "stale_dispatched_recovered"


def _compute_retry_delay_seconds(*, attempts: int) -> int:
    bounded_attempt = max(1, min(attempts, 10))
    return min(
        MAX_RETRY_BACKOFF_SECONDS, RETRY_BASE_SECONDS * (2 ** (bounded_attempt - 1))
    )


def _format_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:MAX_ERROR_MESSAGE_LENGTH]


async def _recover_stale_dispatched_rows(
    *,
    session,  # noqa: ANN001
    limit: int,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    stale_before = current_time - timedelta(seconds=STALE_DISPATCHED_SECONDS)
    stmt = (
        select(ResearchTaskOutbox)
        .join(ResearchSession, ResearchSession.id == ResearchTaskOutbox.session_id)
        .where(
            ResearchTaskOutbox.status == ResearchTaskOutboxStatus.DISPATCHED,
            ResearchTaskOutbox.dispatched_at.is_not(None),
            ResearchTaskOutbox.dispatched_at <= stale_before,
            ResearchTaskOutbox.attempts < ResearchTaskOutbox.max_attempts,
            ResearchSession.status == ResearchSessionStatus.QUEUED,
        )
        .order_by(ResearchTaskOutbox.dispatched_at.asc(), ResearchTaskOutbox.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = ResearchTaskOutboxStatus.FAILED
        row.dispatched_at = None
        row.next_retry_at = current_time
        row.last_error = STALE_RECOVERY_MESSAGE
        logger.warning(
            "Recovered stale dispatched research outbox row",
            extra={
                "outbox_id": str(row.id),
                "session_id": str(row.session_id),
                "attempts": row.attempts,
            },
        )
    return len(rows)


async def _claim_due_outbox_rows(*, session, limit: int) -> list[ResearchTaskOutbox]:  # noqa: ANN001
    now = datetime.now(timezone.utc)
    stmt = (
        select(ResearchTaskOutbox)
        .join(ResearchSession, ResearchSession.id == ResearchTaskOutbox.session_id)
        .where(
            ResearchTaskOutbox.status.in_(
                [ResearchTaskOutboxStatus.PENDING, ResearchTaskOutboxStatus.FAILED]
            ),
            or_(
                ResearchTaskOutbox.next_retry_at.is_(None),
                ResearchTaskOutbox.next_retry_at <= now,
            ),
            ResearchTaskOutbox.attempts < ResearchTaskOutbox.max_attempts,
            ResearchSession.status == ResearchSessionStatus.QUEUED,
        )
        .order_by(ResearchTaskOutbox.created_at.asc(), ResearchTaskOutbox.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        row.status = ResearchTaskOutboxStatus.DISPATCHING
    return rows


@celery_app.task(
    name="app.worker.tasks.research_outbox_dispatcher.dispatch_research_outbox"
)
def dispatch_research_outbox(limit: int = DEFAULT_DISPATCH_BATCH_SIZE) -> None:
    asyncio.run(_dispatch_research_outbox(limit=limit))


async def _dispatch_research_outbox(*, limit: int = DEFAULT_DISPATCH_BATCH_SIZE) -> int:
    settings = get_settings()
    safe_limit = max(int(limit or DEFAULT_DISPATCH_BATCH_SIZE), 1)

    async with managed_task_resources(settings=settings, with_engine=True) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive guard
            return 0

        dispatched_rows = 0
        async with sessionmaker() as session:
            while True:
                await _recover_stale_dispatched_rows(session=session, limit=safe_limit)
                rows = await _claim_due_outbox_rows(session=session, limit=safe_limit)
                if not rows:
                    await session.rollback()
                    break

                from app.worker.tasks.research import run_research_session

                for row in rows:
                    now = datetime.now(timezone.utc)
                    row.attempts += 1
                    try:
                        run_research_session.delay(str(row.session_id))
                    except (
                        Exception
                    ) as exc:  # pragma: no cover - depends on broker state
                        row.status = ResearchTaskOutboxStatus.FAILED
                        row.dispatched_at = None
                        row.last_error = _format_error(exc)
                        row.next_retry_at = now + timedelta(
                            seconds=_compute_retry_delay_seconds(attempts=row.attempts)
                        )
                        logger.warning(
                            "Dispatch research outbox row failed",
                            extra={
                                "outbox_id": str(row.id),
                                "session_id": str(row.session_id),
                                "attempts": row.attempts,
                                "error": row.last_error,
                            },
                        )
                    else:
                        row.status = ResearchTaskOutboxStatus.DISPATCHED
                        row.dispatched_at = now
                        row.last_error = None
                        row.next_retry_at = None
                        dispatched_rows += 1
                await session.commit()

        return dispatched_rows
