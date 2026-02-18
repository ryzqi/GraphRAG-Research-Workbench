"""对话/证据相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class EvidenceSourceKind(str, Enum):
    KB = "kb"
    EXTERNAL = "external"


class KbChatConfig(BaseModel):
    """Session-scoped KB answer chain runtime config."""

    model_config = ConfigDict(extra="forbid")

    query_rewrite_enabled: bool = True
    ambiguity_check_enabled: bool = True
    hyde_enabled: bool = False
    hybrid_retrieval_enabled: bool = True
    rerank_enabled: bool = True
    retrieval_top_k: int = Field(8, ge=1, le=20)
    retrieval_rerank_top_k: int = Field(50, ge=1, le=50)
    retrieval_hybrid_ranker: Literal["rrf", "weighted"] = "rrf"
    retrieval_hybrid_dense_weight: float = Field(0.7, ge=0.0, le=1.0)
    retrieval_hybrid_sparse_weight: float = Field(0.3, ge=0.0, le=1.0)
    retrieval_hybrid_rrf_k: int = Field(60, ge=1, le=200)
    retrieval_parent_max_parents: int = Field(6, ge=1, le=20)
    retrieval_parent_max_children_per_parent: int = Field(2, ge=1, le=10)
    retrieval_multiscale_per_window_top_k: int = Field(30, ge=1, le=200)
    retrieval_multiscale_rrf_k: int = Field(60, ge=1, le=200)
    retrieval_multiscale_max_documents: int = Field(8, ge=1, le=100)
    retrieval_multiscale_max_chunks_per_document: int = Field(2, ge=1, le=20)

    @model_validator(mode="after")
    def validate_constraints(self) -> "KbChatConfig":
        if self.retrieval_rerank_top_k < self.retrieval_top_k:
            raise ValueError("retrieval_rerank_top_k 必须大于等于 retrieval_top_k")
        if self.retrieval_hybrid_ranker == "weighted":
            total_weight = (
                self.retrieval_hybrid_dense_weight + self.retrieval_hybrid_sparse_weight
            )
            if abs(total_weight - 1.0) > 1e-6:
                raise ValueError(
                    "retrieval_hybrid_dense_weight 与 retrieval_hybrid_sparse_weight 之和必须为 1"
                )
        return self


class KbGraphNode(BaseModel):
    id: str
    label: str
    phase: str | None = None
    order: int | None = None


class KbGraphEdge(BaseModel):
    source: str
    target: str
    conditional: bool = False


class KbGraphSchemaResponse(BaseModel):
    version: str
    nodes: list[KbGraphNode]
    edges: list[KbGraphEdge]


def default_kb_chat_config(*, settings: Settings | None = None) -> KbChatConfig:
    cfg = settings if settings is not None else get_settings()
    ranker = str(cfg.retrieval_hybrid_ranker or "rrf").strip().lower()
    if ranker not in {"rrf", "weighted"}:
        ranker = "rrf"
    return KbChatConfig(
        query_rewrite_enabled=bool(cfg.retrieval_query_rewrite_enabled),
        ambiguity_check_enabled=bool(cfg.kb_chat_ambiguity_check_enabled),
        hyde_enabled=bool(cfg.kb_chat_hyde_enabled),
        hybrid_retrieval_enabled=bool(cfg.retrieval_hybrid_enabled),
        rerank_enabled=bool(cfg.retrieval_rerank_enabled),
        retrieval_top_k=int(cfg.retrieval_default_top_k),
        retrieval_rerank_top_k=max(
            int(cfg.retrieval_default_top_k),
            int(cfg.retrieval_max_top_k),
        ),
        retrieval_hybrid_ranker=ranker,
        retrieval_hybrid_dense_weight=float(cfg.retrieval_hybrid_dense_weight),
        retrieval_hybrid_sparse_weight=float(cfg.retrieval_hybrid_sparse_weight),
        retrieval_hybrid_rrf_k=int(cfg.retrieval_hybrid_rrf_k),
        retrieval_parent_max_parents=6,
        retrieval_parent_max_children_per_parent=2,
        retrieval_multiscale_per_window_top_k=30,
        retrieval_multiscale_rrf_k=60,
        retrieval_multiscale_max_documents=8,
        retrieval_multiscale_max_chunks_per_document=2,
    )


def resolve_kb_chat_config(
    *,
    raw: KbChatConfig | dict[str, Any] | None,
    settings: Settings | None = None,
) -> KbChatConfig:
    allowed_keys = set(KbChatConfig.model_fields.keys())
    defaults = default_kb_chat_config(settings=settings).model_dump(mode="json")
    if raw is None:
        return KbChatConfig.model_validate(defaults)
    if isinstance(raw, KbChatConfig):
        payload = raw.model_dump(mode="json")
    elif isinstance(raw, dict):
        payload = {key: value for key, value in raw.items() if key in allowed_keys}
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

    @field_validator("kb_chat_config", mode="before")
    @classmethod
    def _normalize_kb_chat_config(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return resolve_kb_chat_config(raw=value).model_dump(mode="json")
        return value


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
    citation_id: str | None = None
    citation_title: str | None = None
    citation_page_hint: str | None = None
    citation_source: str | None = None


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
