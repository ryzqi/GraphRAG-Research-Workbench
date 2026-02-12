"""资料相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

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


class MaterialWithChunkStatsRead(SourceMaterialRead):
    """带分块统计的资料读取响应。"""

    chunk_count: int = 0


class MaterialListResponse(BaseModel):
    """资料列表响应。"""

    items: list[SourceMaterialRead]
    page: PageMeta


class MaterialWithChunkStatsListResponse(BaseModel):
    """带分块统计的资料列表响应。"""

    items: list[MaterialWithChunkStatsRead]
    page: PageMeta


class DocumentChunkRead(BaseModel):
    """文档分块读取响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    material_id: uuid.UUID
    chunk_index: int
    raw_text: str
    embedding_text: str
    context_text: str | None = None
    context_status: str
    context_error: str | None = None
    context_attempts: int
    chunking_strategy: str
    heading_path: str | None = None
    global_chunk_order: int
    window_id: int | None = None
    window_size_tokens: int | None = None
    window_overlap_tokens: int | None = None
    token_start: int | None = None
    token_end: int | None = None
    source_kind: str | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    locator: dict[str, Any] | None = None
    token_count: int | None = None
    created_at: datetime


class DocumentChunkListResponse(BaseModel):
    """文档分块列表响应。"""

    items: list[DocumentChunkRead]
    page: PageMeta
