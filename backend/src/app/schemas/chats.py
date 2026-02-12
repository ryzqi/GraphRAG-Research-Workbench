"""对话/证据相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.settings import Settings, get_settings


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


class KbChatConfig(BaseModel):
    """Session-scoped KB answer chain feature toggles."""

    query_rewrite_enabled: bool = True
    ambiguity_check_enabled: bool = True
    decomposition_enabled: bool = False
    multi_query_enabled: bool = False
    hyde_enabled: bool = False
    hybrid_retrieval_enabled: bool = True
    rerank_enabled: bool = True
    force_retrieve_enabled: bool = True

    @model_validator(mode="after")
    def validate_mutual_exclusion(self) -> "KbChatConfig":
        if self.decomposition_enabled and self.multi_query_enabled:
            raise ValueError("decomposition_enabled 与 multi_query_enabled 不能同时开启")
        return self


def default_kb_chat_config(*, settings: Settings | None = None) -> KbChatConfig:
    cfg = settings if settings is not None else get_settings()
    return KbChatConfig(
        query_rewrite_enabled=bool(cfg.retrieval_query_rewrite_enabled),
        ambiguity_check_enabled=bool(cfg.kb_chat_ambiguity_check_enabled),
        decomposition_enabled=bool(cfg.kb_chat_decomposition_enabled),
        multi_query_enabled=bool(cfg.kb_chat_multi_query_enabled),
        hyde_enabled=bool(cfg.kb_chat_hyde_enabled),
        hybrid_retrieval_enabled=bool(cfg.retrieval_hybrid_enabled),
        rerank_enabled=bool(cfg.retrieval_rerank_enabled),
        force_retrieve_enabled=bool(cfg.kb_chat_force_retrieve),
    )


def resolve_kb_chat_config(
    *,
    raw: KbChatConfig | dict[str, Any] | None,
    settings: Settings | None = None,
) -> KbChatConfig:
    defaults = default_kb_chat_config(settings=settings).model_dump(mode="json")
    if raw is None:
        return KbChatConfig.model_validate(defaults)
    if isinstance(raw, KbChatConfig):
        payload = raw.model_dump(mode="json")
    elif isinstance(raw, dict):
        payload = raw
    else:
        payload = defaults
    merged = {**defaults, **payload}
    return KbChatConfig.model_validate(merged)


# 会话相关
class ChatSessionCreate(BaseModel):
    session_type: ChatSessionType
    selected_kb_ids: list[uuid.UUID] | None = None
    allow_external: bool = False
    mode: AgentMode
    kb_chat_config: KbChatConfig | None = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_type: ChatSessionType
    selected_kb_ids: list[uuid.UUID] | None = None
    allow_external: bool
    mode: AgentMode
    kb_chat_config: KbChatConfig | None = None
    created_at: datetime
    updated_at: datetime


# 最近对话列表
class ChatSessionRecentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_type: ChatSessionType
    title: str | None = None
    updated_at: datetime


class ChatRecentListResponse(BaseModel):
    items: list[ChatSessionRecentRead]
    web_search_available: bool


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


# 两阶段交互：待审批工具调用
class PendingToolCall(BaseModel):
    """待审批的工具调用。"""

    extension_id: str
    extension_name: str | None = None
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    is_builtin: bool = False


class ToolApprovalRequest(BaseModel):
    """工具审批请求。"""

    approved: bool


class ClarificationResumeRequest(BaseModel):
    """澄清补充请求。"""

    content: str = Field(..., min_length=1)


# 问答响应（完成）
class ChatAnswerResponse(BaseModel):
    status: Literal["succeeded"] = "succeeded"
    assistant_message: ChatMessageRead
    evidence: list[EvidenceItem]
    run: AgentRunRead


class ChatPendingToolApprovalResponse(BaseModel):
    """两阶段交互的第 1 阶段：返回待审批工具清单。"""

    status: Literal["pending_tool_approval"] = "pending_tool_approval"
    thread_id: str
    interrupt_id: str | None = None
    message: str | None = None
    pending_tool_calls: list[PendingToolCall]
    run: AgentRunRead


class ChatPendingUserClarificationResponse(BaseModel):
    """两阶段交互的第 1 阶段：返回待用户补充澄清信息。"""

    status: Literal["pending_user_clarification"] = "pending_user_clarification"
    thread_id: str
    message: str
    run: AgentRunRead
