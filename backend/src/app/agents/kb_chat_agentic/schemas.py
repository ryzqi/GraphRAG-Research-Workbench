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


class TransformQueryDecision(BaseModel):
    """Structured output for retry query transformation."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
