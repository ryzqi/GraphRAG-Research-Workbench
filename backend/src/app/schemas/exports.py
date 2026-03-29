from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator


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

    @model_validator(mode="after")
    def validate_target(self) -> "ExportCreateRequest":
        if self.type == ExportType.CHAT and self.run_id is None:
            raise ValueError("chat 导出必须提供 run_id")
        if self.type == ExportType.RESEARCH and self.session_id is None:
            raise ValueError("research 导出必须提供 session_id")
        return self


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
