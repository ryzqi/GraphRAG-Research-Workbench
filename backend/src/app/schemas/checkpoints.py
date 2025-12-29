"""检查点相关 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CheckpointStateResponse(BaseModel):
    """检查点状态响应。"""

    thread_id: str
    checkpoint_id: str | None = None
    channel_values: dict[str, Any] | None = None
    created_at: datetime | None = None


class CheckpointHistoryItem(BaseModel):
    """检查点历史条目。"""

    checkpoint_id: str
    thread_id: str
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class CheckpointHistoryResponse(BaseModel):
    """检查点历史响应。"""

    thread_id: str
    history: list[CheckpointHistoryItem]


class ResumeRequest(BaseModel):
    """恢复执行请求。"""

    human_input: dict[str, Any]


class ResumeResponse(BaseModel):
    """恢复执行响应。"""

    thread_id: str
    status: str
    message: str
