"""资料相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pagination import PageMeta


class SourceType(str, Enum):
    UPLOAD = "upload"
    URL = "url"
    TEXT = "text"


class MaterialCreateText(BaseModel):
    """创建文本资料请求。"""

    source_type: SourceType = SourceType.TEXT
    title: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class MaterialCreateUrl(BaseModel):
    """创建 URL 资料请求。"""

    source_type: SourceType = SourceType.URL
    title: str = Field(..., min_length=1)
    url: str = Field(..., pattern=r"^https?://")


class SourceMaterialRead(BaseModel):
    """资料读取响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    source_type: SourceType
    title: str
    uri: str | None = None
    mime_type: str | None = None
    created_at: datetime
    updated_at: datetime


class MaterialListResponse(BaseModel):
    """资料列表响应。"""

    items: list[SourceMaterialRead]
    page: PageMeta
