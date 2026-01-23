"""Index rebuild job schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class IndexRebuildStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class IndexRebuildJobRead(BaseModel):
    """Index rebuild job response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    status: IndexRebuildStatus
    error_message: str | None = None
    stats: dict | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
