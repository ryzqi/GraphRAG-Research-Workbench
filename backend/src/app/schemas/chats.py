"""对话/证据相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionType(str, Enum):
    KB_CHAT = "kb_chat"
    GENERAL_CHAT = "general_chat"


class AgentMode(str, Enum):
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT = "multi_agent"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentRunType(str, Enum):
    KB_ANSWER = "kb_answer"
    GENERAL_ANSWER = "general_answer"
    RESEARCH = "research"
    EVALUATION_CASE = "evaluation_case"


class EvidenceSourceKind(str, Enum):
    KB = "kb"
    EXTERNAL = "external"


# 会话相关
class ChatSessionCreate(BaseModel):
    session_type: ChatSessionType
    selected_kb_ids: list[uuid.UUID] | None = None
    allow_external: bool = False
    mode: AgentMode


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_type: ChatSessionType
    selected_kb_ids: list[uuid.UUID] | None = None
    allow_external: bool
    mode: AgentMode
    created_at: datetime
    updated_at: datetime


# 消息相关
class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime


# 证据相关
class EvidenceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_kind: EvidenceSourceKind
    kb_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    locator: dict | None = None
    excerpt: str


# 运行记录相关
class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_type: AgentRunType
    status: AgentRunStatus
    mode: AgentMode
    question: str
    selected_kb_ids: list[uuid.UUID] | None = None
    allow_external: bool
    stage_summaries: dict | None = None
    metrics: dict | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


# 问答响应
class ChatAnswerResponse(BaseModel):
    assistant_message: ChatMessageRead
    evidence: list[EvidenceItem]
    run: AgentRunRead
