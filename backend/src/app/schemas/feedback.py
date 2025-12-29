"""反馈相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FeedbackStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class FeedbackCreate(BaseModel):
    """创建反馈请求。"""

    run_id: uuid.UUID = Field(..., description="关联的 AgentRun ID")
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    comment: str | None = Field(None, description="文本反馈")


class FeedbackUpdate(BaseModel):
    """更新反馈请求（负责人处理）。"""

    status: FeedbackStatus | None = None
    resolution_note: str | None = None


class FeedbackRead(BaseModel):
    """反馈响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    rating: int
    comment: str | None = None
    status: FeedbackStatus
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
