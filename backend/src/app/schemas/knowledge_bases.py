"""知识库相关 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from annotated_types import Ge, Le, MaxLen, MinLen
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.index_rebuilds import IndexRebuildJobRead
from app.schemas.pagination import PageMeta


class ChunkingStrategy(str, Enum):
    QUERY_DEPENDENT_MULTISCALE = "query_dependent_multiscale"
    MAX_MIN_SEMANTIC = "max_min_semantic"
    PARENT_CHILD = "parent_child"
    MARKDOWN_HEADING = "markdown_heading"


class MarkdownHeadingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_heading_level: int = Field(3, ge=1, le=6)
    chunk_size: int = Field(800, ge=200, le=20000)
    chunk_overlap: int = Field(160, ge=0, le=5000)

    @model_validator(mode="before")
    @classmethod
    def _compat_legacy_fields(cls, data: object) -> object:
        """兼容旧版 index_config JSON（如 markdown_heading.enabled / max_section_chars）。"""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        # 历史遗留开关；markdown_heading 现已是互斥的主策略。
        payload.pop("enabled", None)
        # 历史字段名（此前用于表示“每节最大字符数”）。
        if "chunk_size" not in payload and "max_section_chars" in payload:
            payload["chunk_size"] = payload.pop("max_section_chars")
        return payload

    @model_validator(mode="after")
    def _validate_overlap(self) -> "MarkdownHeadingConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class QueryDependentMultiscaleWindowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size_tokens: int = Field(128, ge=16, le=8000)
    chunk_overlap_tokens: int = Field(32, ge=0, le=4000)

    @model_validator(mode="after")
    def _validate_overlap(self) -> "QueryDependentMultiscaleWindowConfig":
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be less than chunk_size_tokens")
        return self


class QueryDependentMultiscaleChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    windows: list[QueryDependentMultiscaleWindowConfig] = Field(
        default_factory=list,
        max_length=5,
    )

    @model_validator(mode="after")
    def _validate_windows(self) -> "QueryDependentMultiscaleChunkingConfig":
        seen: set[tuple[int, int]] = set()
        previous_size: int | None = None
        for window in self.windows:
            key = (window.chunk_size_tokens, window.chunk_overlap_tokens)
            if key in seen:
                raise ValueError(
                    "query_dependent_multiscale.windows contains duplicate windows"
                )
            seen.add(key)

            if previous_size is not None and window.chunk_size_tokens <= previous_size:
                raise ValueError(
                    "query_dependent_multiscale.windows must be sorted by chunk_size_tokens ascending"
                )
            previous_size = window.chunk_size_tokens
        return self


class SemanticThresholdMode(str, Enum):
    PERCENTILE = "percentile"
    HYBRID = "hybrid"
    FIXED = "fixed"


class SemanticConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_tokens: int = Field(80, ge=16, le=1024)
    max_tokens: int = Field(320, ge=16, le=2048)
    threshold_mode: SemanticThresholdMode = SemanticThresholdMode.PERCENTILE
    breakpoint_percentile: int | None = Field(25, ge=1, le=99)
    similarity_threshold: float | None = Field(0.7, ge=0.0, le=1.0)
    overlap_chars: int = Field(96, ge=0, le=2000)
    embedding_batch_size: int = Field(32, ge=8, le=1024)

    @model_validator(mode="after")
    def _validate_range(self) -> "SemanticConfig":
        if self.max_tokens < self.min_tokens:
            raise ValueError("max_tokens must be greater than or equal to min_tokens")

        if (
            self.threshold_mode
            in {
                SemanticThresholdMode.PERCENTILE,
                SemanticThresholdMode.HYBRID,
            }
            and self.breakpoint_percentile is None
        ):
            raise ValueError(
                "breakpoint_percentile is required for percentile/hybrid mode"
            )

        if (
            self.threshold_mode
            in {
                SemanticThresholdMode.FIXED,
                SemanticThresholdMode.HYBRID,
            }
            and self.similarity_threshold is None
        ):
            raise ValueError("similarity_threshold is required for fixed/hybrid mode")

        return self


class ParentChunkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(1200, ge=512, le=20000)
    chunk_overlap: int = Field(120, ge=0, le=5000)

    @model_validator(mode="after")
    def _validate_overlap(self) -> "ParentChunkConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class ChildChunkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(240, ge=128, le=5000)
    chunk_overlap: int = Field(40, ge=0, le=2000)

    @model_validator(mode="after")
    def _validate_overlap(self) -> "ChildChunkConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


def _default_parent_chunk_config() -> ParentChunkConfig:
    return ParentChunkConfig(chunk_size=1200, chunk_overlap=120)


def _default_child_chunk_config() -> ChildChunkConfig:
    return ChildChunkConfig(chunk_size=240, chunk_overlap=40)


class ParentChildConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent: ParentChunkConfig = Field(default_factory=_default_parent_chunk_config)
    child: ChildChunkConfig = Field(default_factory=_default_child_chunk_config)

    @model_validator(mode="after")
    def _validate_parent_child(self) -> "ParentChildConfig":
        if self.parent.chunk_size <= self.child.chunk_size:
            raise ValueError("parent.chunk_size must be greater than child.chunk_size")
        return self


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_heading: MarkdownHeadingConfig = Field(
        default_factory=lambda: MarkdownHeadingConfig(
            max_heading_level=3,
            chunk_size=800,
            chunk_overlap=160,
        )
    )
    general_strategy: ChunkingStrategy = ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
    query_dependent_multiscale: QueryDependentMultiscaleChunkingConfig = Field(
        default_factory=lambda: QueryDependentMultiscaleChunkingConfig(
            windows=[
                QueryDependentMultiscaleWindowConfig(
                    chunk_size_tokens=128,
                    chunk_overlap_tokens=32,
                ),
                QueryDependentMultiscaleWindowConfig(
                    chunk_size_tokens=256,
                    chunk_overlap_tokens=64,
                ),
                QueryDependentMultiscaleWindowConfig(
                    chunk_size_tokens=512,
                    chunk_overlap_tokens=128,
                ),
            ]
        )
    )
    semantic: SemanticConfig = Field(
        default_factory=lambda: SemanticConfig(
            min_tokens=80,
            max_tokens=320,
            threshold_mode=SemanticThresholdMode.PERCENTILE,
            breakpoint_percentile=25,
            similarity_threshold=0.7,
            overlap_chars=96,
            embedding_batch_size=32,
        )
    )
    parent_child: ParentChildConfig = Field(default_factory=ParentChildConfig)

    @model_validator(mode="after")
    def _validate_query_dependent_windows_required(self) -> "ChunkingConfig":
        if (
            self.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
            and not self.query_dependent_multiscale.windows
        ):
            raise ValueError(
                "chunking.query_dependent_multiscale.windows is required when general_strategy is query_dependent_multiscale"
            )
        return self


class ContextualConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_tokens: int = Field(192, ge=0, le=512)
    concurrency: int = Field(2, ge=1, le=10)

    @model_validator(mode="after")
    def _validate_enabled(self) -> "ContextualConfig":
        if self.enabled and self.max_tokens < 1:
            raise ValueError("max_tokens must be greater than 0 when enabled")
        return self


class IndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    contextual: ContextualConfig = Field(
        default_factory=lambda: ContextualConfig(enabled=True, max_tokens=192, concurrency=2)
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_legacy_retrieval(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        # 检索调优项已迁移到 kb_chat 会话配置。
        payload.pop("retrieval", None)
        return payload


class IndexConfigNumberConstraint(BaseModel):
    min: int | float
    max: int | float


class MarkdownHeadingConfigConstraints(BaseModel):
    max_heading_level: IndexConfigNumberConstraint
    chunk_size: IndexConfigNumberConstraint
    chunk_overlap: IndexConfigNumberConstraint


class QueryDependentMultiscaleWindowConfigConstraints(BaseModel):
    chunk_size_tokens: IndexConfigNumberConstraint
    chunk_overlap_tokens: IndexConfigNumberConstraint


class QueryDependentMultiscaleConfigConstraints(BaseModel):
    window_count_max: int
    window: QueryDependentMultiscaleWindowConfigConstraints


class SemanticConfigConstraints(BaseModel):
    min_tokens: IndexConfigNumberConstraint
    max_tokens: IndexConfigNumberConstraint
    breakpoint_percentile: IndexConfigNumberConstraint
    similarity_threshold: IndexConfigNumberConstraint
    overlap_chars: IndexConfigNumberConstraint
    embedding_batch_size: IndexConfigNumberConstraint


class ParentChunkConfigConstraints(BaseModel):
    chunk_size: IndexConfigNumberConstraint
    chunk_overlap: IndexConfigNumberConstraint


class ChildChunkConfigConstraints(BaseModel):
    chunk_size: IndexConfigNumberConstraint
    chunk_overlap: IndexConfigNumberConstraint


class ParentChildConfigConstraints(BaseModel):
    parent: ParentChunkConfigConstraints
    child: ChildChunkConfigConstraints


class ContextualConfigConstraints(BaseModel):
    max_tokens: IndexConfigNumberConstraint
    concurrency: IndexConfigNumberConstraint


class IndexConfigConstraints(BaseModel):
    markdown_heading: MarkdownHeadingConfigConstraints
    query_dependent_multiscale: QueryDependentMultiscaleConfigConstraints
    semantic: SemanticConfigConstraints
    parent_child: ParentChildConfigConstraints
    contextual: ContextualConfigConstraints


class KnowledgeBaseTextLengthConstraint(BaseModel):
    min_length: int | None = None
    max_length: int


class KnowledgeBaseFormConstraints(BaseModel):
    name: KnowledgeBaseTextLengthConstraint
    description: KnowledgeBaseTextLengthConstraint


def _index_config_number_constraint(
    model_type: type[BaseModel], field_name: str
) -> IndexConfigNumberConstraint:
    field = model_type.model_fields[field_name]
    minimum: int | float | None = None
    maximum: int | float | None = None

    for metadata in field.metadata:
        if isinstance(metadata, Ge):
            minimum = metadata.ge
        elif isinstance(metadata, Le):
            maximum = metadata.le

    if minimum is None or maximum is None:
        raise RuntimeError(f"{model_type.__name__}.{field_name} 缺少 ge/le 约束")

    return IndexConfigNumberConstraint(min=minimum, max=maximum)


def _field_max_length(model_type: type[BaseModel], field_name: str) -> int:
    field = model_type.model_fields[field_name]
    for metadata in field.metadata:
        if isinstance(metadata, MaxLen):
            return int(metadata.max_length)
    raise RuntimeError(f"{model_type.__name__}.{field_name} 缺少 max_length 约束")


def _text_length_constraint(
    model_type: type[BaseModel], field_name: str
) -> KnowledgeBaseTextLengthConstraint:
    field = model_type.model_fields[field_name]
    minimum: int | None = None
    maximum: int | None = None

    for metadata in field.metadata:
        if isinstance(metadata, MinLen):
            minimum = int(metadata.min_length)
        elif isinstance(metadata, MaxLen):
            maximum = int(metadata.max_length)

    if maximum is None:
        raise RuntimeError(f"{model_type.__name__}.{field_name} 缺少 max_length 约束")

    return KnowledgeBaseTextLengthConstraint(min_length=minimum, max_length=maximum)


def index_config_constraints() -> IndexConfigConstraints:
    return IndexConfigConstraints(
        markdown_heading=MarkdownHeadingConfigConstraints(
            max_heading_level=_index_config_number_constraint(
                MarkdownHeadingConfig, "max_heading_level"
            ),
            chunk_size=_index_config_number_constraint(MarkdownHeadingConfig, "chunk_size"),
            chunk_overlap=_index_config_number_constraint(
                MarkdownHeadingConfig, "chunk_overlap"
            ),
        ),
        query_dependent_multiscale=QueryDependentMultiscaleConfigConstraints(
            window_count_max=_field_max_length(
                QueryDependentMultiscaleChunkingConfig, "windows"
            ),
            window=QueryDependentMultiscaleWindowConfigConstraints(
                chunk_size_tokens=_index_config_number_constraint(
                    QueryDependentMultiscaleWindowConfig, "chunk_size_tokens"
                ),
                chunk_overlap_tokens=_index_config_number_constraint(
                    QueryDependentMultiscaleWindowConfig, "chunk_overlap_tokens"
                ),
            ),
        ),
        semantic=SemanticConfigConstraints(
            min_tokens=_index_config_number_constraint(SemanticConfig, "min_tokens"),
            max_tokens=_index_config_number_constraint(SemanticConfig, "max_tokens"),
            breakpoint_percentile=_index_config_number_constraint(
                SemanticConfig, "breakpoint_percentile"
            ),
            similarity_threshold=_index_config_number_constraint(
                SemanticConfig, "similarity_threshold"
            ),
            overlap_chars=_index_config_number_constraint(SemanticConfig, "overlap_chars"),
            embedding_batch_size=_index_config_number_constraint(
                SemanticConfig, "embedding_batch_size"
            ),
        ),
        parent_child=ParentChildConfigConstraints(
            parent=ParentChunkConfigConstraints(
                chunk_size=_index_config_number_constraint(ParentChunkConfig, "chunk_size"),
                chunk_overlap=_index_config_number_constraint(
                    ParentChunkConfig, "chunk_overlap"
                ),
            ),
            child=ChildChunkConfigConstraints(
                chunk_size=_index_config_number_constraint(ChildChunkConfig, "chunk_size"),
                chunk_overlap=_index_config_number_constraint(
                    ChildChunkConfig, "chunk_overlap"
                ),
            ),
        ),
        contextual=ContextualConfigConstraints(
            max_tokens=_index_config_number_constraint(ContextualConfig, "max_tokens"),
            concurrency=_index_config_number_constraint(ContextualConfig, "concurrency"),
        ),
    )


def knowledge_base_form_constraints() -> KnowledgeBaseFormConstraints:
    return KnowledgeBaseFormConstraints(
        name=_text_length_constraint(KnowledgeBaseCreate, "name"),
        description=_text_length_constraint(KnowledgeBaseCreate, "description"),
    )


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_optional_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        payload = dict(data)

        if "name" in payload and isinstance(payload["name"], str):
            payload["name"] = payload["name"].strip()

        if "description" in payload and isinstance(payload["description"], str):
            normalized_description = payload["description"].strip()
            payload["description"] = normalized_description or None

        if "tags" in payload and isinstance(payload["tags"], list):
            normalized_tags: list[str] = []
            for tag in payload["tags"]:
                if not isinstance(tag, str):
                    return payload
                normalized_tag = tag.strip()
                if normalized_tag:
                    normalized_tags.append(normalized_tag)
            payload["tags"] = normalized_tags or None

        return payload


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
