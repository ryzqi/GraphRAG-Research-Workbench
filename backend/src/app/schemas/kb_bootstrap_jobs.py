from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ingestion_batches import EntryErrorRead, ManifestSourceType
from app.schemas.knowledge_bases import KnowledgeBaseCreate


class BootstrapSubmissionStatus(str, Enum):
    QUEUED_UPLOAD = "queued_upload"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BootstrapManifestTextEntry(BaseModel):
    source_type: Literal[ManifestSourceType.TEXT.value] = ManifestSourceType.TEXT.value
    entry_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=500)
    text: str


class BootstrapManifestUrlEntry(BaseModel):
    source_type: Literal[ManifestSourceType.URL.value] = ManifestSourceType.URL.value
    entry_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=500)
    url: str


class BootstrapManifestFileEntry(BaseModel):
    source_type: Literal[ManifestSourceType.FILE.value] = ManifestSourceType.FILE.value
    entry_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=500)
    filename: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(gt=0)
    content_type: str | None = Field(default=None, max_length=128)
    sha256: str | None = Field(default=None, max_length=128)


BootstrapManifestEntry = Annotated[
    BootstrapManifestTextEntry | BootstrapManifestUrlEntry | BootstrapManifestFileEntry,
    Field(discriminator="source_type"),
]


class BootstrapSubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: uuid.UUID
    entries: Annotated[list[BootstrapManifestEntry], Field(min_length=1)]


class BootstrapCreateKnowledgeBaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb: KnowledgeBaseCreate
    entries: Annotated[list[BootstrapManifestEntry], Field(min_length=1)]


class BootstrapUploadTarget(BaseModel):
    entry_id: str
    material_id: uuid.UUID
    filename: str
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    object_key: str
    expires_at: datetime


class BootstrapSubmissionUploadProgress(BaseModel):
    total_files: int = 0
    uploaded_files: int = 0
    failed_files: int = 0


class BootstrapSubmissionCreateResponse(BaseModel):
    job_id: uuid.UUID
    kb_id: uuid.UUID
    status: BootstrapSubmissionStatus
    upload_targets: list[BootstrapUploadTarget] = Field(default_factory=list)
    upload_progress: BootstrapSubmissionUploadProgress = Field(
        default_factory=BootstrapSubmissionUploadProgress
    )


class BootstrapSubmissionFinalizeResponse(BaseModel):
    job_id: uuid.UUID
    kb_id: uuid.UUID
    status: BootstrapSubmissionStatus
    upload_progress: BootstrapSubmissionUploadProgress = Field(
        default_factory=BootstrapSubmissionUploadProgress
    )


class BootstrapCreateKnowledgeBaseResponse(BaseModel):
    kb_id: uuid.UUID
    job_id: uuid.UUID
    status: BootstrapSubmissionStatus
    monitor_url: str


class BootstrapUploadSessionResponse(BaseModel):
    job_id: uuid.UUID
    kb_id: uuid.UUID
    status: BootstrapSubmissionStatus
    upload_targets: list[BootstrapUploadTarget] = Field(default_factory=list)
    upload_progress: BootstrapSubmissionUploadProgress = Field(
        default_factory=BootstrapSubmissionUploadProgress
    )


class BootstrapSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    batch_id: uuid.UUID | None = None
    status: BootstrapSubmissionStatus
    total_entries: int
    accepted_entries: int
    failed_entries: int
    entry_errors: list[EntryErrorRead] = Field(default_factory=list)
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    upload_progress: BootstrapSubmissionUploadProgress = Field(
        default_factory=BootstrapSubmissionUploadProgress
    )
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
