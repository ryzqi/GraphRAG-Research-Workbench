"""Research v2 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.research_session import ResearchSessionStatus
from app.schemas.chats import AgentMode


class ResearchSessionCreateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    selected_kb_ids: list[uuid.UUID]
    allow_external: bool = False
    mode: AgentMode


class ResearchSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    session_id: uuid.UUID = Field(alias="id")
    thread_id: str
    question: str
    selected_kb_ids: list[uuid.UUID] | None = None
    allow_external: bool
    mode: AgentMode
    status: ResearchSessionStatus
    stage_summaries: dict | None = None
    metrics: dict | None = None
    final_output: str | None = None
    error_message: str | None = None
    trace_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime


class ResearchEventEnvelope(BaseModel):
    event_id: str
    sequence: int
    timestamp: datetime
    event_type: str
    session_id: uuid.UUID
    payload: dict
    trace_id: str | None = None
    idempotency_key: str | None = None


class ResearchInterruptRequest(BaseModel):
    reason: str | None = None


class ResearchResumeRequest(BaseModel):
    resume_from_event_id: str | None = None
    idempotency_key: str = Field(..., min_length=8, max_length=128)
    decision: Literal["continue", "adjust", "terminate"] = "continue"
    instructions: str | None = None


class ResearchArtifactsRead(BaseModel):
    session_id: uuid.UUID
    report_md: str | None = None
    report_json: dict | None = None
    updated_at: datetime | None = None

