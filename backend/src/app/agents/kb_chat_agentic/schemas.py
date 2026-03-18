"""Structured output schemas for KB chat agentic nodes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DocGraderReason = Literal[
    "passed",
    "no_evidence",
    "not_relevant",
    "insufficient",
    "too_broad",
    "needs_clarification",
    "fallback_open",
    "fallback_closed",
]

DocGraderRiskLevel = Literal["low", "medium", "high"]
DocGraderRetryAdvice = Literal["none", "retry", "clarify"]


class DocGraderDecision(BaseModel):
    """Structured output for retrieval relevance grading."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: DocGraderReason
    missing_constraints: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_level: DocGraderRiskLevel = "medium"
    retry_advice: DocGraderRetryAdvice = "retry"


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
    """Structured output for final answer review."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: AnswerReviewReason
    missing_citations: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


class AnswerReviewSubDecision(BaseModel):
    """Structured output for one answer-review sub-check."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: AnswerReviewReason
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_citations: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)


class ReverseQuestionDecision(BaseModel):
    """Structured output for ambiguity clarification generation."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)


ClarificationReasonCode = Literal[
    "missing_entity",
    "missing_scope",
    "missing_time",
    "missing_metric",
    "coref_uncertain",
    "mixed",
]


class ClarificationSlotDecision(BaseModel):
    """Structured slot required to disambiguate the question."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=32)
    label: str = Field(..., min_length=1, max_length=64)
    required: bool = True
    options: list[str] = Field(default_factory=list, max_length=6)


class AmbiguityDecision(BaseModel):
    """Structured output for model-driven ambiguity decision."""

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
    """Structured output for retry query transformation."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)


class ReferenceResolutionDecision(BaseModel):
    """Structured output for LLM-driven reference resolution."""

    model_config = ConfigDict(extra="forbid")

    resolved_query: str = Field(..., min_length=1, max_length=256)
    triggered: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    selected_mention: str = Field(default="", max_length=120)
    needs_clarification: bool = False
    reasoning: str = Field(default="", max_length=240)


NormalizeRecallRisk = Literal["low", "medium", "high"]


class NormalizeDecision(BaseModel):
    """Structured output for query normalization."""

    model_config = ConfigDict(extra="forbid")

    canonical_query: str = Field(..., min_length=1, max_length=256)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=8)
    time_constraints: list[str] = Field(default_factory=list, max_length=6)
    metric_constraints: list[str] = Field(default_factory=list, max_length=6)
    scope_constraints: list[str] = Field(default_factory=list, max_length=6)
    recall_risk: NormalizeRecallRisk = "medium"
    drift_risk: bool = False
    reasoning: str = Field(default="", max_length=240)


class MergeContextResolutionDecision(BaseModel):
    """Structured output for merge-context conflict resolution."""

    model_config = ConfigDict(extra="forbid")

    summary_text: str = Field(default="", max_length=1200)
    keep_memory: bool = True
    notes: list[str] = Field(default_factory=list, max_length=4)


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
        default="kb_chat_complexity_classify_v4",
        min_length=1,
        max_length=64,
        description="路由策略版本标识，便于可观测与回溯。",
    )


class DecompositionDecision(BaseModel):
    """Structured output for query decomposition."""

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
    """Structured output for multi-query generation."""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(default_factory=list, min_length=1, max_length=6)


class EntityExpansionCandidate(BaseModel):
    """Single entity expansion candidate with confidence."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=256)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=120)


class EntityExpandDecision(BaseModel):
    """Structured output for entity expansion."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[EntityExpansionCandidate] = Field(
        default_factory=list, max_length=12
    )
    dropped_queries: list[str] = Field(default_factory=list, max_length=12)
    reasoning: str = Field(default="", max_length=240)


class HyDEDecision(BaseModel):
    """Structured output for HyDE hypothetical document generation."""

    model_config = ConfigDict(extra="forbid")

    hypothetical_document: str = Field(..., min_length=1)


class HyDEBatchDecision(BaseModel):
    """Structured output for batched HyDE hypothetical document generation."""

    model_config = ConfigDict(extra="forbid")

    hypothetical_documents: list[str] = Field(default_factory=list, min_length=1, max_length=8)


class RetrievalPlanDecision(BaseModel):
    """Structured output for retrieval budget planning."""

    model_config = ConfigDict(extra="forbid")

    per_query_top_k: int = Field(..., ge=1, le=50)
    global_candidates_limit: int = Field(..., ge=1, le=300)
    rerank_input_limit: int = Field(..., ge=1, le=300)
    reasoning: str = Field(default="", max_length=240)
