"""Deep Research workspace 结构化工件契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchEvidenceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1, max_length=32)
    claim_ids: list[str] = Field(..., min_length=1)
    citation_index: int = Field(..., ge=0)
    excerpt_ref: int = Field(default=0, ge=0)
    relation: Literal["supports", "contradicts", "qualifies", "contextualizes"]
    confidence: Literal["high", "medium", "low"]
    notes: str | None = Field(default=None, max_length=1000)


class ResearchClaimEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(..., min_length=1, max_length=32)
    section_id: str | None = Field(default=None, min_length=1, max_length=64)
    claim: str = Field(..., min_length=1, max_length=500)
    status: Literal["pending", "supported", "contested", "insufficient", "dropped"]
    confidence: Literal["high", "medium", "low"]
    independence_providers: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_supported_independence(self) -> "ResearchClaimEntry":
        if self.status != "supported":
            return self
        providers = {
            provider.strip().lower()
            for provider in self.independence_providers
            if provider and provider.strip()
        }
        providers.discard("workspace")
        if len(providers) < 2:
            raise ValueError(
                "supported claim 必须至少来自 2 个不同的非 workspace provider"
            )
        if not self.supporting_evidence_ids:
            raise ValueError("supported claim 必须引用至少一条 evidence")
        return self


class ResearchClaimMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ResearchClaimEntry] = Field(default_factory=list)
    generated_at: datetime


class ResearchEvidenceLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidences: list[ResearchEvidenceEntry] = Field(default_factory=list)
    generated_at: datetime
