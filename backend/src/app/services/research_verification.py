"""Deep Research verification artifacts（基于 LLM alignment judge）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.schemas.research import ResearchCanonicalCitation
from app.schemas.research_workspace import (
    ResearchClaimEntry,
    ResearchEvidenceEntry,
)
from app.services.research_alignment_judge import ClaimAlignmentVerdict


class AlignmentJudgeProtocol(Protocol):
    async def judge_all(
        self,
        *,
        claims: Sequence[ResearchClaimEntry],
        evidences: Sequence[ResearchEvidenceEntry],
        citations: Sequence[ResearchCanonicalCitation],
    ) -> list[ClaimAlignmentVerdict]: ...


@dataclass(slots=True, frozen=True)
class VerificationArtifacts:
    claim_map: list[dict[str, object]]
    coverage_matrix: dict[str, object]
    conflicts: list[dict[str, object]]
    source_ledger: list[dict[str, object]]


def _conflict_reason(verdict: ClaimAlignmentVerdict) -> str:
    if verdict.conflicting_evidence_ids:
        return "conflicting_evidence"
    if verdict.missing_aspects:
        return "insufficient_evidence"
    return "contested"


def _build_source_ledger(
    citations: Sequence[ResearchCanonicalCitation],
) -> list[dict[str, object]]:
    return [
        {
            "provider": citation.source_provider,
            "origin_url": citation.origin_url,
            "title": citation.title,
            "source_type": citation.source_type.value,
            "excerpt_count": len(citation.excerpts),
        }
        for citation in citations
    ]


async def build_verification_artifacts_async(
    *,
    claims: Sequence[ResearchClaimEntry],
    evidences: Sequence[ResearchEvidenceEntry],
    citations: Sequence[ResearchCanonicalCitation],
    coverage_gaps: Sequence[str],
    provider_counts: dict[str, int],
    judge: AlignmentJudgeProtocol,
) -> VerificationArtifacts:
    verdicts = await judge.judge_all(
        claims=claims,
        evidences=evidences,
        citations=citations,
    )
    verdict_by_claim = {verdict.claim_id: verdict for verdict in verdicts}
    claim_map: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    missing_aspects_total = 0
    supported_count = 0
    for claim in claims:
        verdict = verdict_by_claim.get(claim.claim_id)
        if verdict is None:
            verdict = ClaimAlignmentVerdict(
                claim_id=claim.claim_id,
                verdict="insufficient",
                supporting_evidence_ids=[],
                conflicting_evidence_ids=[],
                missing_aspects=["judge_missing"],
                reason="judge 未返回该 claim 的裁决",
            )
        missing_aspects_total += len(verdict.missing_aspects)
        claim_map.append(
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "verdict": verdict.verdict,
                "supporting_evidence_ids": verdict.supporting_evidence_ids,
                "conflicting_evidence_ids": verdict.conflicting_evidence_ids,
                "missing_aspects": verdict.missing_aspects,
                "reason": verdict.reason,
            }
        )
        if verdict.verdict == "supported":
            supported_count += 1
            continue
        conflicts.append(
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "verdict": verdict.verdict,
                "reason": _conflict_reason(verdict),
                "missing_aspects": verdict.missing_aspects,
            }
        )
    alignment_pass_rate = supported_count / len(claims) if claims else 0.0
    coverage_matrix = {
        "provider_counts": dict(provider_counts),
        "missing_providers": list(coverage_gaps),
        "alignment_pass_rate": alignment_pass_rate,
        "missing_aspects_total": missing_aspects_total,
    }
    return VerificationArtifacts(
        claim_map=claim_map,
        coverage_matrix=coverage_matrix,
        conflicts=conflicts,
        source_ledger=_build_source_ledger(citations),
    )


def build_verification_artifacts(**_: object) -> VerificationArtifacts:
    raise RuntimeError(
        "build_verification_artifacts 已废弃；请改用 build_verification_artifacts_async 并提供 alignment judge"
    )
