from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel
DECOMPOSITION_MAX_SUB_QUERIES = 5
MULTI_QUERY_FIXED_VARIANTS = 3
HYDE_NUM_HYPOTHESES = 5
HYDE_AGGREGATION = "mean_embedding"
HYDE_REGENERATE_ON_RETRY = True
STRUCTURED_CALL_RETRYABLE_REASONS = frozenset(
    {"error", "empty_structured_response", "invalid_schema"}
)
STRUCTURED_CALL_MAX_ATTEMPTS = 2


@dataclass(slots=True)
class RewriteResult:
    query: str
    rewritten: bool
    reason: str | None = None
    latency_ms: int | None = None
    meta: dict[str, object] | None = None


@dataclass(slots=True)
class QueryListResult:
    queries: list[str]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None
    plan: dict[str, object] | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(slots=True)
class AmbiguityResult:
    ambiguous: bool
    reverse_question: str | None = None
    reason: str | None = None
    failure_reason: str | None = None
    latency_ms: int | None = None
    reason_code: str | None = None
    confidence: float | None = None
    model_reason: str | None = None
    fallback_used: bool = False
    clarification_payload: dict[str, object] | None = None


@dataclass(slots=True)
class ComplexityRouteResult:
    strategy: str
    success: bool
    reasoning: str | None = None
    failure_reason: str | None = None
    confidence: float = 0.0
    risk_flags: list[str] | None = None
    decision_version: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class StructuredCallResult:
    payload: BaseModel | None = None
    success: bool = False
    reason: str | None = None
    latency_ms: int | None = None


class _AsyncInvoker(Protocol):
    async def ainvoke(self, input: object) -> object: ...


@dataclass(slots=True)
class MergeContextResolutionResult:
    summary_text: str
    keep_memory: bool
    notes: list[str]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None


@dataclass(slots=True)
class RetrievalPlanResult:
    budget: dict[str, int]
    success: bool
    reason: str | None = None
    latency_ms: int | None = None
    meta: dict[str, object] | None = None
