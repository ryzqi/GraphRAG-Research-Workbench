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


class ToolExtensionListResponse(BaseModel):
    """扩展列表响应。"""

    items: list[ToolExtensionRead]
    page: PageMeta


class ToolDescriptorListResponse(BaseModel):
    """扩展工具列表响应。"""

    items: list[ToolDescriptor]
    page: PageMeta
