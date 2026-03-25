from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


SemanticCacheContextMode = Literal["standalone", "contextual"]


@dataclass(frozen=True)
class SemanticCacheScope:
    scope_fingerprint: str
    kb_version: str
    mode: str
    allow_external: bool
    config_fingerprint: str


@dataclass(frozen=True)
class SemanticCacheContext:
    mode: SemanticCacheContextMode
    signature: str | None = None


@dataclass(frozen=True)
class SemanticCacheLookupRequest:
    question: str
    question_vector: list[float]
    scope: SemanticCacheScope
    context: SemanticCacheContext
    similarity_threshold: float
    ttl_seconds: int


@dataclass(frozen=True)
class SemanticCacheStoreRequest:
    question: str
    answer: str
    question_vector: list[float]
    scope: SemanticCacheScope
    context: SemanticCacheContext
    evidence: list[dict[str, Any]]
    citation_ids: list[str]
    evidence_fingerprint: list[str]
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]
    source_run_id: str | None
    ttl_seconds: int


@dataclass
class SemanticCacheHit:
    answer: str
    evidence: list[dict[str, Any]]
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]
    score: float
    threshold: float
    ttl_seconds: int
    entry_id: str | None = None
    schema_version: str | None = None
    hit_type: str | None = None
    created_at: str | None = None
    context_fingerprint: str | None = None
    kb_version: str | None = None
