"""队列健康诊断辅助函数。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import anyio
from celery import Celery
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, get_settings
from app.integrations.redis_client import RedisClient
from app.models.ingestion_batch import IngestionBatchDoc, IngestionDocStatus
from app.models.kb_bootstrap_job import KBBootstrapJob, KBBootstrapJobStatus
from app.schemas.system import QueueHealthRead, QueueStateRead, QueueStuckSummaryRead
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

REQUIRED_QUEUES: tuple[str, ...] = ("default", "dispatch", "ingestion")


def _collect_consumer_counts(
    active_queues_by_node: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not active_queues_by_node:
        return counts

    for queues in active_queues_by_node.values():
        for item in queues or ():
            queue_name = str(item.get("name") or "").strip()
            if not queue_name:
                continue
            counts[queue_name] = counts.get(queue_name, 0) + 1
    return counts


def _build_queue_states(
    *,
    consumer_counts: Mapping[str, int],
    queue_lengths: Mapping[str, int],
    required_queues: tuple[str, ...] = REQUIRED_QUEUES,
) -> dict[str, QueueStateRead]:
    all_queues = set(required_queues)
    all_queues.update(consumer_counts.keys())
    all_queues.update(queue_lengths.keys())

    states: dict[str, QueueStateRead] = {}
    for queue_name in sorted(all_queues):
        consumer_count = max(int(consumer_counts.get(queue_name, 0) or 0), 0)
        ready_messages = max(int(queue_lengths.get(queue_name, 0) or 0), 0)
        required = queue_name in required_queues
        healthy = consumer_count > 0 if required else True
        states[queue_name] = QueueStateRead(
            consumer_count=consumer_count,
            ready_messages=ready_messages,
            required=required,
            healthy=healthy,
        )
    return states


class QueueHealthService:
    def __init__(
        self,
        db: AsyncSession,
        redis: RedisClient,
        *,
        celery: Celery | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._redis = redis
        self._celery = celery or celery_app
        self._settings = settings or get_settings()

    async def get_queue_health(self) -> QueueHealthRead:
        now = datetime.now(timezone.utc)
        consumer_counts = await self._get_consumer_counts()
        queue_lengths = await self._get_queue_lengths(queues=set(REQUIRED_QUEUES) | set(consumer_counts))
        queue_states = _build_queue_states(
            consumer_counts=consumer_counts,
            queue_lengths=queue_lengths,
            required_queues=REQUIRED_QUEUES,
        )
        workers_online = any(state.consumer_count > 0 for state in queue_states.values())

        stuck_summary = await self._get_stuck_summary(now=now)
        return QueueHealthRead(
            workers_online=workers_online,
            queues=queue_states,
            stuck_summary=stuck_summary,
            timestamp=now,
        )

    async def _get_consumer_counts(self) -> dict[str, int]:
        try:
            payload = await anyio.to_thread.run_sync(
                self._inspect_active_queues_sync,
                abandon_on_cancel=True,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Queue health inspect failed", extra={"error": str(exc)})
            return {}
        return _collect_consumer_counts(payload)

    def _inspect_active_queues_sync(self) -> dict[str, Sequence[Mapping[str, Any]]]:
        inspect = self._celery.control.inspect(timeout=1.0)
        payload = inspect.active_queues() if inspect is not None else None
        if not isinstance(payload, dict):
            return {}
        return payload

    async def _get_queue_lengths(self, *, queues: set[str]) -> dict[str, int]:
        lengths: dict[str, int] = {}
        for queue_name in sorted(queue for queue in queues if queue):
            try:
                value = await self._redis.llen(queue_name)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "Queue health redis read failed",
                    extra={"queue": queue_name, "error": str(exc)},
                )
                value = 0
            lengths[queue_name] = max(int(value or 0), 0)
        return lengths

    async def _get_stuck_summary(self, *, now: datetime) -> QueueStuckSummaryRead:
        bootstrap_deadline = now - timedelta(
            seconds=max(int(self._settings.bootstrap_queued_timeout_seconds), 1)
        )
        doc_deadline = now - timedelta(
            seconds=max(int(self._settings.ingestion_doc_queue_timeout_seconds), 1)
        )

        bootstrap_stmt = select(func.count(KBBootstrapJob.id)).where(
            KBBootstrapJob.status.in_(
                [KBBootstrapJobStatus.QUEUED, KBBootstrapJobStatus.RUNNING]
            ),
            KBBootstrapJob.updated_at <= bootstrap_deadline,
        )
        doc_stmt = select(func.count(IngestionBatchDoc.id)).where(
            IngestionBatchDoc.status == IngestionDocStatus.PROCESSING,
            IngestionBatchDoc.updated_at <= doc_deadline,
        )

        bootstrap_count = int((await self._db.execute(bootstrap_stmt)).scalar_one() or 0)
        processing_doc_count = int((await self._db.execute(doc_stmt)).scalar_one() or 0)
        return QueueStuckSummaryRead(
            bootstrap_queued_jobs=bootstrap_count,
            processing_docs_over_sla=processing_doc_count,
        )

