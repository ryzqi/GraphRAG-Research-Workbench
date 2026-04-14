"""统一 ingestion batch API 的 schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ManifestSourceType(str, Enum):
    TEXT = "text"
    URL = "url"
    FILE = "file"


class BatchStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class DocStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ManifestTextEntry(BaseModel):
    source_type: Literal["text"] = ManifestSourceType.TEXT.value
    entry_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=500)
    text: str


class ManifestUrlEntry(BaseModel):
    source_type: Literal["url"] = ManifestSourceType.URL.value
    entry_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=500)
    url: str


class ManifestFileEntry(BaseModel):
    source_type: Literal["file"] = ManifestSourceType.FILE.value
    entry_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=500)
    material_id: uuid.UUID


ManifestEntry = Annotated[
    ManifestTextEntry | ManifestUrlEntry | ManifestFileEntry,
    Field(discriminator="source_type"),
]


class IngestionBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: uuid.UUID
    entries: list[ManifestEntry] = Field(min_length=1)


class EntryErrorRead(BaseModel):
    entry_id: str
    source_type: ManifestSourceType
    code: str
    message: str
    retryable: bool
    details: dict | None = None


class IngestionBatchSubmitResponse(BaseModel):
    batch_id: uuid.UUID
    kb_id: uuid.UUID
    status: BatchStatus
    is_bootstrap: bool
    config_snapshot_id: uuid.UUID
    config_version: int
    total_docs: int
    accepted_docs: int
    failed_docs: int
    entry_errors: list[EntryErrorRead]


class IngestionBatchDocRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_type: ManifestSourceType
    source_ref: str | None = None
    title: str | None = None
    fingerprint: str
    status: DocStatus
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int
    retryable: bool
    chunk_count: int
    context_failed_chunks: list[dict] | None = None
    config_version: int
    created_at: datetime
    updated_at: datetime


class IngestionBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    config_snapshot_id: uuid.UUID
    config_version: int
    is_bootstrap: bool
    status: BatchStatus
    total_docs: int
    succeeded_docs: int
    failed_docs: int
    canceled_docs: int
    succeeded_chunks: int
    error_summary: dict | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    docs: list[IngestionBatchDocRead]


class KnowledgeBaseIngestionStateRead(BaseModel):
    kb_id: uuid.UUID
    has_active_batch: bool
    active_batch_id: uuid.UUID | None = None
    active_batch_status: BatchStatus | None = None
    updated_at: datetime


class IngestionBatchRetryResponse(BaseModel):
    batch_id: uuid.UUID
    status: BatchStatus
    requeued_docs: int
    ignored_docs: int


class IngestionBatchCancelResponse(BaseModel):
    batch_id: uuid.UUID
    status: BatchStatus
    canceled_docs: int
    finished_at: datetime | None = None
