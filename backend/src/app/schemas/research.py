"""深度研究接口与事件契约。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.models.research_session import ResearchSessionStatus
from app.utils.text_sanitization import has_visible_text


def _normalize_optional_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def _normalize_required_text(value: Any, *, field_name: str) -> str:
    normalized = _normalize_optional_text(value, field_name=field_name)
    if normalized is None or not has_visible_text(normalized):
        raise ValueError(f"{field_name} 不能为空")
    return normalized


class ResearchSourceTarget(str, Enum):
    KB = "kb"
    WEB = "web"
    PAPER = "paper"
    HYBRID = "hybrid"


class ResearchComplexity(str, Enum):
    SIMPLE = "simple"
    COMPARATIVE = "comparative"
    COMPLEX = "complex"


class ResearchSourceType(str, Enum):
    KB = "kb"
    WEB = "web"
    PAPER = "paper"


class ResearchSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    plan_first: bool = True

    @field_validator("question")
    @classmethod
    def _validate_question(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="question")


class ResearchPlanSubtask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    target_sources: list[ResearchSourceTarget] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="title")

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="description")


class ResearchPlanSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_brief: str = Field(..., min_length=1)
    complexity: ResearchComplexity
    summary: str = Field(..., min_length=1)
    subtasks: list[ResearchPlanSubtask] = Field(default_factory=list)
    target_sources: list[ResearchSourceTarget] = Field(min_length=1)
    budget_guidance: str | None = None
    confirmation_required: bool = False

    @field_validator("research_brief")
    @classmethod
    def _validate_research_brief(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="research_brief")

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="summary")

    @field_validator("budget_guidance")
    @classmethod
    def _validate_budget_guidance(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="budget_guidance")


class ResearchClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    question: str = Field(..., min_length=1)
    why_it_matters: str = Field(..., min_length=1)

    @field_validator("id", "question", "why_it_matters")
    @classmethod
    def _validate_question_fields(cls, value: str, info: ValidationInfo) -> str:
        return _normalize_required_text(value, field_name=info.field_name)


class ResearchClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1)
    questions: list[ResearchClarificationQuestion] = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="summary")


class ResearchClarificationSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(..., min_length=1)

    @field_validator("answer")
    @classmethod
    def _validate_answer(cls, value: str) -> str:
        return _normalize_required_text(value, field_name="answer")


class ResearchSessionAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    status: ResearchSessionStatus
    plan_snapshot: ResearchPlanSnapshot | None = None
    clarification_request: ResearchClarificationRequest | None = None

    @model_validator(mode="after")
    def _validate_status_payload(self) -> "ResearchSessionAccepted":
        if (
            self.status == ResearchSessionStatus.CLARIFYING
            and self.clarification_request is None
        ):
            raise ValueError("clarifying 状态必须包含 clarification_request")
        if (
            self.status == ResearchSessionStatus.AWAITING_CONFIRMATION
            and self.plan_snapshot is None
        ):
            raise ValueError("awaiting_confirmation 状态必须包含 plan_snapshot")
        return self


class ResearchPlanConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _validate_note(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="note")


class ResearchCanonicalCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: ResearchSourceType
    source_provider: str = Field(..., min_length=1, max_length=64)
    retrieval_method: str = Field(..., min_length=1, max_length=64)
    source_id: str = Field(..., min_length=1, max_length=256)
    title: str | None = None
    url: str | None = None
    origin_url: str | None = None
    arxiv_id: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    pdf_url: str | None = None
    accessed_at: datetime | None = None

    @field_validator(
        "source_provider",
        "retrieval_method",
        "source_id",
        "title",
        "url",
        "origin_url",
        "arxiv_id",
        "pdf_url",
        mode="before",
    )
    @classmethod
    def _validate_text_fields(cls, value: Any, info) -> Any:  # type: ignore[no-untyped-def]
        if info.field_name in {"title", "url", "origin_url", "arxiv_id", "pdf_url"}:
            return _normalize_optional_text(value, field_name=info.field_name)
        return _normalize_required_text(value, field_name=info.field_name)

    @field_validator("authors", mode="before")
    @classmethod
    def _validate_authors(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("authors 必须是字符串列表")
        normalized: list[str] = []
        for item in value:
            normalized.append(_normalize_required_text(item, field_name="authors[]"))
        return normalized

    @model_validator(mode="after")
    def validate_source_specific_fields(self) -> "ResearchCanonicalCitation":
        if self.source_type == ResearchSourceType.WEB and not self.origin_url:
            raise ValueError("网页来源 citation 必须包含 origin_url")
        if self.source_type == ResearchSourceType.PAPER and self.arxiv_id and not self.pdf_url:
            raise ValueError("论文 citation 提供 arxiv_id 时必须同时提供 pdf_url")
        return self


class ResearchEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=128)
    sequence: int = Field(..., ge=1)
    timestamp: datetime
    event_type: str = Field(..., min_length=1, max_length=128)
    session_id: uuid.UUID
    phase: str = Field(..., min_length=1, max_length=64)
    namespace: str = Field(..., min_length=1, max_length=255)
    payload: dict[str, Any]
    trace_id: str | None = Field(default=None, max_length=128)
    source_provider: str | None = Field(default=None, max_length=64)
    retrieval_method: str | None = Field(default=None, max_length=64)
    origin_url: str | None = None
    lc_agent_name: str | None = Field(default=None, max_length=128)
    subagent_name: str | None = Field(default=None, max_length=128)

    @field_validator(
        "event_id",
        "event_type",
        "phase",
        "namespace",
        "trace_id",
        "source_provider",
        "retrieval_method",
        "origin_url",
        "lc_agent_name",
        "subagent_name",
        mode="before",
    )
    @classmethod
    def _validate_event_text(cls, value: Any, info) -> Any:  # type: ignore[no-untyped-def]
        if info.field_name in {
            "trace_id",
            "source_provider",
            "retrieval_method",
            "origin_url",
            "lc_agent_name",
            "subagent_name",
        }:
            return _normalize_optional_text(value, field_name=info.field_name)
        return _normalize_required_text(value, field_name=info.field_name)


class ResearchStreamResumeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_from_event_id: str | None = Field(default=None, max_length=128)

    @field_validator("resume_from_event_id", mode="before")
    @classmethod
    def _validate_resume_from_event_id(cls, value: Any) -> str | None:
        return _normalize_optional_text(value, field_name="resume_from_event_id")

    def effective_after_event_id(self, *, last_event_id: str | None) -> str | None:
        normalized_last_event_id = _normalize_optional_text(
            last_event_id, field_name="Last-Event-ID"
        )
        return normalized_last_event_id or self.resume_from_event_id


class ResearchInterruptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="reason")


class ResearchResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=1, max_length=128)
    resume_from_event_id: str | None = Field(default=None, max_length=128)
    decisions: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def _validate_idempotency_key(cls, value: Any) -> str:
        return _normalize_required_text(value, field_name="idempotency_key")

    @field_validator("resume_from_event_id", mode="before")
    @classmethod
    def _validate_resume_from_event_id(cls, value: Any) -> str | None:
        return _normalize_optional_text(value, field_name="resume_from_event_id")


class ResearchArtifactRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: str = Field(..., min_length=1, max_length=64)
    content_text: str | None = None
    content_json: dict[str, Any] | list[Any] | None = None
    citations: list[ResearchCanonicalCitation] = Field(default_factory=list)
    source_provider: str | None = Field(default=None, max_length=64)
    retrieval_method: str | None = Field(default=None, max_length=64)
    origin_url: str | None = None

    @field_validator(
        "artifact_key",
        "content_text",
        "source_provider",
        "retrieval_method",
        "origin_url",
        mode="before",
    )
    @classmethod
    def _validate_artifact_text(cls, value: Any, info) -> Any:  # type: ignore[no-untyped-def]
        if info.field_name == "artifact_key":
            return _normalize_required_text(value, field_name="artifact_key")
        return _normalize_optional_text(value, field_name=info.field_name)


class ResearchArtifactsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    items: list[ResearchArtifactRead] = Field(default_factory=list)
