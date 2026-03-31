"""Research verification artifacts helpers。"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.research import ResearchCanonicalCitation


@dataclass(slots=True, frozen=True)
class VerificationArtifacts:
    claim_map: list[dict[str, object]]
    coverage_matrix: dict[str, object]
    conflicts: list[dict[str, object]]
    source_ledger: list[dict[str, object]]


def build_verification_artifacts(
    *,
    findings: list[str],
    citations: list[ResearchCanonicalCitation],
    coverage_gaps: list[str],
    provider_counts: dict[str, int],
) -> VerificationArtifacts:
    citation_indices = list(range(min(len(citations), 2)))
    claim_map = [
        {
            "claim": finding,
            "verdict": "supported" if len(citations) >= 2 else "insufficient",
            "citation_indices": citation_indices,
        }
        for finding in findings
    ]
    coverage_matrix = {
        "provider_counts": dict(provider_counts),
        "missing_providers": list(coverage_gaps),
    }
    source_ledger = [
        {
            "provider": citation.source_provider,
            "origin_url": citation.origin_url,
            "title": citation.title,
            "source_type": citation.source_type.value,
        }
        for citation in citations
    ]
    return VerificationArtifacts(
        claim_map=claim_map,
        coverage_matrix=coverage_matrix,
        conflicts=[],
        source_ledger=source_ledger,
    )
