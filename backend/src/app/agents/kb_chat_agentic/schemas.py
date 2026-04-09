"""KB Chat agentic 节点的结构化输出 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AnswerReviewReason = Literal[
    "passed",
    "no_evidence",
    "insufficient_evidence",
    "unsupported_claims",
    "citation_mismatch",
    "missing_citations",
    "invalid_citations",
    "off_topic",
    "incomplete",
    "non_answer",
    "needs_clarification",
]


class AnswerReviewDecision(BaseModel):
    """最终答案审查的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: AnswerReviewReason
    missing_citations: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


class AnswerReviewSubDecision(BaseModel):
    """单个答案审查子检查的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: AnswerReviewReason
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_citations: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    affected_paragraph_ids: list[str] = Field(default_factory=list, max_length=12)
    details: dict[str, object] = Field(default_factory=dict)


ClarificationReasonCode = Literal[
    "missing_entity",
    "missing_scope",
    "missing_time",
    "missing_metric",
    "coref_uncertain",
    "mixed",
]


class ClarificationSlotDecision(BaseModel):
    """用于消解问题歧义的结构化槽位。"""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=32)
    label: str = Field(..., min_length=1, max_length=64)
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=6)


class AmbiguityDecision(BaseModel):
    """模型驱动歧义判断的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    ambiguous: bool
    reason_code: ClarificationReasonCode = "mixed"
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=240)
    clarifying_question: str = Field(default="", max_length=180)
    missing_slots: list[ClarificationSlotDecision] = Field(
        default_factory=list, max_length=6
    )
    suggested_answers: list[str] = Field(default_factory=list, max_length=4)


class TransformQueryDecision(BaseModel):
    """重试时查询改写的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)


class ReferenceResolutionDecision(BaseModel):
    """LLM 驱动指代消解的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    resolved_query: str = Field(..., min_length=1, max_length=256)
    triggered: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    selected_mention: str = Field(default="", max_length=120)
    needs_clarification: bool = False
    reasoning: str = Field(default="", max_length=240)


NormalizeRecallRisk = Literal["low", "medium", "high"]


class NormalizeDecision(BaseModel):
    """问题规范化的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    canonical_query: str = Field(..., min_length=1, max_length=256)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=8)
    time_constraints: list[str] = Field(default_factory=list, max_length=6)
    metric_constraints: list[str] = Field(default_factory=list, max_length=6)
    scope_constraints: list[str] = Field(default_factory=list, max_length=6)
    recall_risk: NormalizeRecallRisk = "medium"
    drift_risk: bool = False
    constraint_preserved: bool = True
    has_multi_target: bool = False
    is_comparison: bool = False
    reasoning: str = Field(default="", max_length=512)


class MergeContextResolutionDecision(BaseModel):
    """合并上下文冲突消解的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    summary_text: str = Field(default="", max_length=1200)
    keep_memory: bool = True
    notes: list[str] = Field(default_factory=list, max_length=4)


COMPLEXITY_CLASSIFY_DECISION_VERSION = "kb_chat_complexity_classify_v5"


ComplexityStrategy = Literal["direct", "decomposition", "multi_query"]


class ComplexityDecision(BaseModel):
    """复杂度分类结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="简要分析：目标数量、是否需分步推理、是否存在召回风险",
    )
    strategy: ComplexityStrategy = "direct"
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="路由置信度，范围 [0,1]。",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="路由关键风险信号，如 comparison/multi_target/recall_risk_high。",
    )
    decision_version: str = Field(
        default=COMPLEXITY_CLASSIFY_DECISION_VERSION,
        min_length=1,
        max_length=64,
        description="路由策略版本标识，便于可观测与回溯。",
    )


class DecompositionDecision(BaseModel):
    """问题拆解的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    sub_queries: list[str] = Field(default_factory=list, min_length=1, max_length=5)
    strategy: Literal["direct", "decomposition", "multi_query", "hybrid"] = (
        "decomposition"
    )
    plan_version: str = Field(default="kb_chat_decomposition_plan_v2", max_length=64)
    sub_query_specs: list[dict[str, object]] = Field(default_factory=list, max_length=5)
    risk_flags: list[str] = Field(default_factory=list, max_length=8)
    reasoning: str = Field(default="", max_length=240)


class MultiQueryDecision(BaseModel):
    """多路查询生成的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(default_factory=list, min_length=1, max_length=6)


class HyDEBatchDecision(BaseModel):
    """批量 HyDE 假设文档生成的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    hypothetical_documents: list[str] = Field(
        default_factory=list, min_length=1, max_length=8
    )


class RetrievalPlanDecision(BaseModel):
    """检索预算规划的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    per_query_top_k: int = Field(..., ge=1, le=50)
    global_candidates_limit: int = Field(..., ge=1, le=300)
    rerank_input_limit: int = Field(..., ge=1, le=300)
    reasoning: str = Field(default="", max_length=240)


class ContextCompressItem(BaseModel):
    """上下文压缩阶段选中的结构化证据项。"""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(..., min_length=2, max_length=16)
    excerpt: str = Field(..., min_length=1, max_length=4000)


class ContextCompressDecision(BaseModel):
    """上下文压缩的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["keep_all", "subset", "no_evidence"] = "keep_all"
    items: list[ContextCompressItem] = Field(default_factory=list, max_length=32)


ClaimRole = Literal["main", "auxiliary"]
ClaimSupportStatus = Literal["supported", "weak_supported", "unsupported"]
ParagraphReviewStatus = Literal["passed", "needs_repair", "failed"]


class ParagraphClaim(BaseModel):
    """答案段落内单条断言的结构化审查单元。"""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(..., min_length=1, max_length=64)
    claim_text: str = Field(..., min_length=1, max_length=4000)
    role: ClaimRole = "main"
    support_status: ClaimSupportStatus = "supported"
    supporting_citation_ids: list[str] = Field(default_factory=list, max_length=16)


class AnswerParagraph(BaseModel):
    """用于答案审查 / 渲染的结构化段落单元。"""

    model_config = ConfigDict(extra="forbid")

    paragraph_id: str = Field(default="", max_length=64)
    text: str = Field(default="", max_length=8000)
    citation_ids: list[str] = Field(default_factory=list, max_length=32)
    claims: list[ParagraphClaim] = Field(default_factory=list, max_length=16)
    review_status: ParagraphReviewStatus = "passed"


class DraftAnswerDecision(BaseModel):
    """草稿答案生成的结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    paragraphs: list[AnswerParagraph] = Field(default_factory=list, max_length=12)


class AnswerRenderMeta(BaseModel):
    """由答案段落推导出的 latest-only 渲染元数据。"""

    model_config = ConfigDict(extra="forbid")

    paragraph_count: int = Field(default=0, ge=0)
    claim_count: int = Field(default=0, ge=0)
    citation_count: int = Field(default=0, ge=0)
    citation_mode: Literal["paragraph_aggregate"] = "paragraph_aggregate"
