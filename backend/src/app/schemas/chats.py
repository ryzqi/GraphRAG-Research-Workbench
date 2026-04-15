"""对话/证据相关 Schemas。"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.settings import Settings, get_settings
from app.utils.text_sanitization import has_visible_text


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


class EvidenceSourceKind(str, Enum):
    KB = "kb"
    EXTERNAL = "external"


class KbChatConfig(BaseModel):
    """会话级 KB 答案链运行时配置。"""

    model_config = ConfigDict(extra="forbid")

    retrieval_top_k: int = Field(12, ge=1, le=20)
    retrieval_rerank_top_k: int = Field(40, ge=1, le=40)
    retrieval_hybrid_rrf_k: int = Field(60, ge=1, le=200)
    retrieval_parent_max_parents: int = Field(8, ge=1, le=20)
    retrieval_parent_max_children_per_parent: int = Field(3, ge=1, le=10)
    retrieval_multiscale_per_window_top_k: int = Field(40, ge=1, le=200)
    retrieval_multiscale_rrf_k: int = Field(60, ge=1, le=200)
    retrieval_multiscale_max_documents: int = Field(12, ge=1, le=100)
    retrieval_multiscale_max_chunks_per_document: int = Field(2, ge=1, le=20)

    @model_validator(mode="after")
    def validate_constraints(self) -> "KbChatConfig":
        if self.retrieval_rerank_top_k < self.retrieval_top_k:
            raise ValueError("retrieval_rerank_top_k 必须大于等于 retrieval_top_k")
        return self


class KbGraphNode(BaseModel):
    id: str
    label: str
    phase: str | None = None
    order: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KbGraphEdge(BaseModel):
    source: str
    target: str
    conditional: bool = False


class KbGraphSchemaResponse(BaseModel):
    version: str
    hash: str
    nodes: list[KbGraphNode]
    edges: list[KbGraphEdge]


def default_kb_chat_config(*, settings: Settings | None = None) -> KbChatConfig:
    cfg = settings if settings is not None else get_settings()
    return KbChatConfig(
        retrieval_top_k=int(cfg.retrieval_default_top_k),
        retrieval_rerank_top_k=max(
            int(cfg.retrieval_default_top_k),
            int(cfg.retrieval_max_top_k),
        ),
        retrieval_hybrid_rrf_k=int(cfg.retrieval_hybrid_rrf_k),
        retrieval_parent_max_parents=8,
        retrieval_parent_max_children_per_parent=3,
        retrieval_multiscale_per_window_top_k=40,
        retrieval_multiscale_rrf_k=60,
        retrieval_multiscale_max_documents=12,
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
        unknown_keys = set(raw.keys()) - allowed_keys
        if unknown_keys:
            KbChatConfig.model_validate(raw)
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


WebSearchStatusMode = Literal["healthy", "degraded", "down"]


class WebSearchProviderStatusRead(BaseModel):
    name: Literal["tavily", "searxng", "jina_reader"]
    configured: bool
    verified: bool
    healthy: bool
    mode: WebSearchStatusMode
    latency_ms: int | None = None
    error: str | None = None


class WebSearchStatusRead(BaseModel):
    configured: bool
    verified: bool
    mode: WebSearchStatusMode
    providers: list[WebSearchProviderStatusRead] = Field(default_factory=list)


class ChatRecentListResponse(BaseModel):
    items: list[ChatSessionRecentRead]
    web_search: WebSearchStatusRead


# 消息相关
class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        if not has_visible_text(value):
            raise ValueError("content 不能为空")
        return value

    @field_validator("client_request_id", mode="before")
    @classmethod
    def _normalize_client_request_id(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("client_request_id 必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("client_request_id 不能为空")
        return normalized


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
    source_excerpt: str | None = None
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


class ToolDecision(BaseModel):
    """单个工具调用的审批决策。"""

    type: Literal["approve", "reject", "edit"]
    message: str | None = None
    edited_action: dict[str, Any] | None = None


class InterruptDecisionBatch(BaseModel):
    """单个 interrupt 的审批决策集合。"""

    interrupt_id: str = Field(..., min_length=1)
    decisions: list[ToolDecision] = Field(default_factory=list, min_length=1)


class ToolApprovalRequest(BaseModel):
    """工具审批请求。"""

    interrupts: list[InterruptDecisionBatch] = Field(default_factory=list, min_length=1)


class PendingInterruptApproval(BaseModel):
    """单个 interrupt 对应的待审批信息。"""

    interrupt_id: str
    message: str | None = None
    pending_tool_calls: list[PendingToolCall] = Field(default_factory=list)


class ClarificationResumeRequest(BaseModel):
    """澄清补充请求。"""

    content: str = Field(..., min_length=1)


# 问答响应（完成）
ClarificationReasonCode = Literal[
    "missing_entity",
    "missing_scope",
    "missing_time",
    "missing_metric",
    "coref_uncertain",
    "mixed",
]


class ClarificationSlot(BaseModel):
    """供用户填写以消除歧义的结构化槽位。"""

    key: str = Field(..., min_length=1, max_length=32)
    label: str = Field(..., min_length=1, max_length=64)
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=6)


class PendingClarification(BaseModel):
    """供 UI 引导消歧使用的结构化澄清载荷。"""

    question: str = Field(..., min_length=1)
    reason_code: ClarificationReasonCode = "mixed"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    model_reason: str | None = None
    slots: list[ClarificationSlot] = Field(default_factory=list)
    suggested_answers: list[str] = Field(default_factory=list, max_length=4)


class SemanticCacheMeta(BaseModel):
    hit: bool = False
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    ttl_seconds: int | None = Field(default=None, ge=0)
    entry_id: str | None = Field(default=None, max_length=128)
    schema_version: str | None = Field(default=None, max_length=32)
    hit_type: Literal["strong_hit"] | None = None
    created_at: datetime | str | None = None


class ChatAnswerResponse(BaseModel):
    status: Literal["succeeded"] = "succeeded"
    assistant_message: ChatMessageRead
    evidence: list[EvidenceItem]
    source: Literal["live", "cached"] = "live"
    cache: SemanticCacheMeta | None = None
    stage_summaries: dict | None = None
    metrics: dict | None = None
    run: AgentRunRead


class ChatPendingToolApprovalResponse(BaseModel):
    """两阶段交互的第 1 阶段：返回待审批工具清单。"""

    status: Literal["pending_tool_approval"] = "pending_tool_approval"
    thread_id: str
    pending_interrupts: list[PendingInterruptApproval]
    run: AgentRunRead


class ChatPendingUserClarificationResponse(BaseModel):
    """两阶段交互的第 1 阶段：返回待用户补充澄清信息。"""

    status: Literal["pending_user_clarification"] = "pending_user_clarification"
    thread_id: str
    message: str
    pending_clarification: PendingClarification | None = None
    assistant_message: ChatMessageRead | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    source: Literal["live", "cached"] = "live"
    cache: SemanticCacheMeta | None = None
    stage_summaries: dict | None = None
    metrics: dict | None = None
    run: AgentRunRead
