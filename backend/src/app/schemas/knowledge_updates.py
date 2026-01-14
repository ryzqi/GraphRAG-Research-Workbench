"""候选知识更新 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PageMeta


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class ProposalCreate(BaseModel):
    """创建候选沉淀请求。"""

    kb_id: uuid.UUID
    source_run_id: uuid.UUID
    summary: str = Field(..., min_length=1)
    payload: dict


class ProposalUpdate(BaseModel):
    """更新候选沉淀请求。"""

    status: ProposalStatus | None = None
    reviewed_by: str | None = None


class ProposalRead(BaseModel):
    """候选沉淀响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    source_run_id: uuid.UUID | None
    summary: str
    payload: dict
    status: ProposalStatus
    created_by: str | None
    reviewed_by: str | None
    created_at: datetime
    reviewed_at: datetime | None


class ProposalListResponse(BaseModel):
    """候选沉淀列表响应。"""

    items: list[ProposalRead]
    page: PageMeta
