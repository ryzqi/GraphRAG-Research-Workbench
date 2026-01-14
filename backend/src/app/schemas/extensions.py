"""扩展管理相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PageMeta


class ExtensionTransport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


class ExtensionStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class InvocationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


# 扩展管理
class ToolExtensionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    transport: ExtensionTransport
    endpoint: str = Field(..., min_length=1)
    scope: dict | None = None


class ToolExtensionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    transport: ExtensionTransport | None = None
    endpoint: str | None = Field(None, min_length=1)
    status: ExtensionStatus | None = None
    scope: dict | None = None


class ToolExtensionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    transport: ExtensionTransport
    endpoint: str
    status: ExtensionStatus
    scope: dict | None = None
    created_at: datetime
    updated_at: datetime


# 工具描述
class ToolDescriptor(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict | None = None


# 调用记录
class ToolInvocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extension_id: uuid.UUID
    run_id: uuid.UUID
    tool_name: str
    purpose: str | None = None
    input: dict | None = None
    output: dict | None = None
    status: InvocationStatus
    error_message: str | None = None
    requires_confirmation: bool
    user_confirmed: bool | None = None
    started_at: datetime
    finished_at: datetime | None = None


# 调用摘要（用于响应展示）
class ToolInvocationSummary(BaseModel):
    tool_name: str
    purpose: str | None = None
    status: InvocationStatus
    extension_name: str | None = None


class ToolExtensionListResponse(BaseModel):
    """扩展列表响应。"""

    items: list[ToolExtensionRead]
    page: PageMeta


class ToolDescriptorListResponse(BaseModel):
    """扩展工具列表响应。"""

    items: list[ToolDescriptor]
    page: PageMeta
