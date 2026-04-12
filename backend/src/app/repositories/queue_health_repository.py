from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_batch import IngestionBatchDoc, IngestionDocStatus
from app.models.kb_bootstrap_job import KBBootstrapJob, KBBootstrapJobStatus
from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.system import QueueStuckSummaryRead


class QueueHealthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def build_stuck_summary(
        self,
        *,
        bootstrap_deadline: datetime,
        doc_deadline: datetime,
        research_deadline: datetime,
    ) -> QueueStuckSummaryRead:
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
        research_stmt = select(func.count(ResearchSession.id)).where(
            ResearchSession.status == ResearchSessionStatus.QUEUED,
            ResearchSession.updated_at <= research_deadline,
        )

        bootstrap_count = int(
            (await self._db.execute(bootstrap_stmt)).scalar_one() or 0
        )
        processing_doc_count = int((await self._db.execute(doc_stmt)).scalar_one() or 0)
        research_count = int((await self._db.execute(research_stmt)).scalar_one() or 0)
        return QueueStuckSummaryRead(
            bootstrap_queued_jobs=bootstrap_count,
            processing_docs_over_sla=processing_doc_count,
            research_queued_sessions=research_count,
        )
