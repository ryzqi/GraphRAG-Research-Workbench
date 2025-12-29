"""研究相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chats import AgentMode


class ResearchRunCreateRequest(BaseModel):
    """创建研究任务请求。"""

    question: str = Field(..., min_length=1)
    selected_kb_ids: list[uuid.UUID]
    allow_external: bool = False
    mode: AgentMode


class ResearchReportRead(BaseModel):
    """研究报告响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    content_md: str
    citations: list[dict]
    created_at: datetime
