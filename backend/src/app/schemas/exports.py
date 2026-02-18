from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class ExportType(str, Enum):
    CHAT = "chat"
    RESEARCH = "research"


class ExportStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExportCreateRequest(BaseModel):
    type: ExportType
    run_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None


class ExportJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    status: ExportStatus
    download_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
