"""知识库相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.index_rebuilds import IndexRebuildJobRead
from app.schemas.pagination import PageMeta


class ChunkingStrategy(str, Enum):
    SLIDING_WINDOW = "sliding_window"
    MAX_MIN_SEMANTIC = "max_min_semantic"
    PARENT_CHILD = "parent_child"
    MARKDOWN_HEADING = "markdown_heading"


class MarkdownHeadingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_heading_level: int = Field(3, ge=1, le=6)
    chunk_size: int = Field(4000, ge=200, le=20000)
    chunk_overlap: int = Field(200, ge=0, le=5000)

    @model_validator(mode="before")
    @classmethod
    def _compat_legacy_fields(cls, data: object) -> object:
        """Compatibility for old index_config JSON (e.g. markdown_heading.enabled/max_section_chars)."""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        # Legacy toggle; markdown_heading is now a mutual-exclusive main strategy.
        payload.pop("enabled", None)
        # Legacy field name (previously used as "max chars per section").
        if "chunk_size" not in payload and "max_section_chars" in payload:
            payload["chunk_size"] = payload.pop("max_section_chars")
        return payload

    @model_validator(mode="after")
    def _validate_overlap(self) -> "MarkdownHeadingConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class SlidingWindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(512, ge=128, le=20000)
    chunk_overlap: int = Field(64, ge=0, le=2000)

    @model_validator(mode="after")
    def _validate_overlap(self) -> "SlidingWindowConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class SemanticConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_tokens: int = Field(80, ge=16, le=1024)
    max_tokens: int = Field(256, ge=16, le=2048)
    similarity_threshold: float = Field(0.6, ge=0.0, le=1.0)
    overlap_chars: int = Field(64, ge=0, le=2000)

    @model_validator(mode="after")
    def _validate_range(self) -> "SemanticConfig":
        if self.max_tokens < self.min_tokens:
            raise ValueError("max_tokens must be greater than or equal to min_tokens")
        return self


class ParentChunkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(2000, ge=512, le=20000)
    chunk_overlap: int = Field(200, ge=0, le=5000)

    @model_validator(mode="after")
    def _validate_overlap(self) -> "ParentChunkConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class ChildChunkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(400, ge=128, le=5000)
    chunk_overlap: int = Field(50, ge=0, le=2000)

    @model_validator(mode="after")
    def _validate_overlap(self) -> "ChildChunkConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class ParentChildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent: ParentChunkConfig = Field(default_factory=ParentChunkConfig)
    child: ChildChunkConfig = Field(default_factory=ChildChunkConfig)

    @model_validator(mode="after")
    def _validate_parent_child(self) -> "ParentChildConfig":
        if self.parent.chunk_size <= self.child.chunk_size:
            raise ValueError("parent.chunk_size must be greater than child.chunk_size")
        return self


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_heading: MarkdownHeadingConfig = Field(default_factory=MarkdownHeadingConfig)
    general_strategy: ChunkingStrategy = ChunkingStrategy.SLIDING_WINDOW
    sliding_window: SlidingWindowConfig = Field(default_factory=SlidingWindowConfig)
    semantic: SemanticConfig = Field(default_factory=SemanticConfig)
    parent_child: ParentChildConfig = Field(default_factory=ParentChildConfig)


class ContextualConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_tokens: int = Field(128, ge=0, le=512)
    concurrency: int = Field(3, ge=1, le=10)

    @model_validator(mode="after")
    def _validate_enabled(self) -> "ContextualConfig":
        if self.enabled and self.max_tokens < 1:
            raise ValueError("max_tokens must be greater than 0 when enabled")
        return self


class RetrievalParentChildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_parents: int = Field(6, ge=1, le=20)
    max_children_per_parent: int = Field(2, ge=1, le=10)


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_child: RetrievalParentChildConfig = Field(
        default_factory=RetrievalParentChildConfig
    )


class IndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    contextual: ContextualConfig = Field(default_factory=ContextualConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)

class KnowledgeBaseStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class KnowledgeBaseReadiness(str, Enum):
    NOT_READY = "not_ready"
    READY = "ready"


class KnowledgeBaseStatusFilter(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    ALL = "all"


class KnowledgeBaseReadinessFilter(str, Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    ALL = "all"


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(None, max_length=500)
    tags: list[str] | None = None
    index_config: IndexConfig | None = None


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=500)
    tags: list[str] | None = None


class KnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    tags: list[str] | None = None
    status: KnowledgeBaseStatus
    readiness: KnowledgeBaseReadiness
    readiness_updated_at: datetime
    current_config_version: int
    index_config: IndexConfig | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseIndexConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_config: IndexConfig


class KnowledgeBaseIndexConfigUpdateResponse(BaseModel):
    knowledge_base: KnowledgeBaseRead
    rebuild_job: IndexRebuildJobRead | None = None


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseRead]
    page: PageMeta
