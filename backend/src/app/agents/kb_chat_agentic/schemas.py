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
]


class DocGraderDecision(BaseModel):
    """Structured output for retrieval relevance grading."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: DocGraderReason
    missing_constraints: list[str] = Field(default_factory=list)


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
    """复杂度路由结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="简要分析：目标数量、是否需分步推理、是否存在召回风险",
    )
    strategy: ComplexityStrategy = "direct"


class DecompositionDecision(BaseModel):
    """Structured output for query decomposition."""

    model_config = ConfigDict(extra="forbid")

    sub_queries: list[str] = Field(default_factory=list, min_length=1, max_length=5)


class MultiQueryDecision(BaseModel):
    """Structured output for multi-query generation."""

    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(default_factory=list, min_length=1, max_length=6)


class HyDEDecision(BaseModel):
    """Structured output for HyDE hypothetical document generation."""

    model_config = ConfigDict(extra="forbid")

    hypothetical_document: str = Field(..., min_length=1)


class HyDEBatchDecision(BaseModel):
    """Structured output for batched HyDE hypothetical document generation."""

    model_config = ConfigDict(extra="forbid")

    hypothetical_documents: list[str] = Field(default_factory=list, min_length=1, max_length=8)
