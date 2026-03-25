"""系统诊断 API 的 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class QueueStateRead(BaseModel):
    consumer_count: int = Field(0, ge=0)
    ready_messages: int = Field(0, ge=0)
    required: bool = False
    healthy: bool = False


class QueueStuckSummaryRead(BaseModel):
    bootstrap_queued_jobs: int = Field(0, ge=0)
    processing_docs_over_sla: int = Field(0, ge=0)


class QueueHealthRead(BaseModel):
    workers_online: bool
    queues: dict[str, QueueStateRead]
    stuck_summary: QueueStuckSummaryRead
    timestamp: datetime

