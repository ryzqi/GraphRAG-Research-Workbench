"""导入任务相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PageMeta


class IngestionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class IngestionMode(str, Enum):
    CREATE = "create"
    UPDATE = "update"


class IngestionJobCreateRequest(BaseModel):
    """创建导入任务请求。"""

    kb_id: uuid.UUID
    material_ids: list[uuid.UUID] = Field(..., min_length=1)
    mode: IngestionMode = IngestionMode.CREATE


class IngestionJobRead(BaseModel):
    """导入任务读取响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    status: IngestionStatus
    error_message: str | None = None
    stats: dict | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class IngestionJobListResponse(BaseModel):
    """导入任务列表响应。"""

    items: list[IngestionJobRead]
    page: PageMeta
