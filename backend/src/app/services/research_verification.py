"""Research verification artifacts helpers。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.research import ResearchCanonicalCitation


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
_NAMED_TOKEN_PATTERN = re.compile(r"[A-Z][A-Za-z0-9]+(?:[A-Z][A-Za-z0-9]+)*")
_GENERIC_TOKENS = {
    "claim",
    "coverage",
    "deep",
    "execution",
    "first",
    "ledger",
    "plan",
    "planner",
    "planning",
    "provider",
    "report",
    "research",
    "runtime",
    "search",
    "source",
    "structured",
    "web",
    "workspace",
    "workflow",
    "支持",
    "提供",
    "执行",
    "缺少",
    "覆盖",
    "证据",
}


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
    citation_tokens = [_citation_tokens(citation) for citation in citations]
    claim_map: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    claimed_gap_indices: set[int] = set()
    for finding in findings:
        claim_tokens = _tokenize(finding)
        citation_indices = [
            index
            for index, tokens in enumerate(citation_tokens)
            if claim_tokens and claim_tokens.intersection(tokens)
        ]
        related_gap_indices = [
            index
            for index, gap in enumerate(coverage_gaps)
            if claim_tokens and claim_tokens.intersection(_tokenize(gap))
        ]
        matched_claim_tokens = set()
        for index in citation_indices:
            matched_claim_tokens.update(claim_tokens.intersection(citation_tokens[index]))
        uncovered_named_tokens = sorted(
            _named_tokens(finding).difference(matched_claim_tokens)
        )
        verdict = _determine_verdict(
            citation_indices=citation_indices,
            related_gap_indices=related_gap_indices,
            uncovered_named_tokens=uncovered_named_tokens,
        )
        claim_map.append(
            {
                "claim": finding,
                "verdict": verdict,
                "citation_indices": citation_indices,
            }
        )
        if verdict == "supported":
            continue
        claimed_gap_indices.update(related_gap_indices)
        conflicts.append(
            {
                "claim": finding,
                "verdict": verdict,
                "reason": _conflict_reason(
                    citation_indices=citation_indices,
                    related_gap_indices=related_gap_indices,
                    uncovered_named_tokens=uncovered_named_tokens,
                ),
                "citation_indices": citation_indices,
                "coverage_gaps": [coverage_gaps[index] for index in related_gap_indices],
            }
        )
    unresolved_coverage_gaps = [
        gap
        for index, gap in enumerate(coverage_gaps)
        if index not in claimed_gap_indices
    ]
    if unresolved_coverage_gaps:
        conflicts.append(
            {
                "claim": None,
                "verdict": "contested",
                "reason": "coverage_gap",
                "citation_indices": [],
                "coverage_gaps": unresolved_coverage_gaps,
            }
        )
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
        conflicts=conflicts,
        source_ledger=source_ledger,
    )


def _tokenize(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(str(value).lower())
        if token and token not in _GENERIC_TOKENS
    }


def _citation_tokens(citation: ResearchCanonicalCitation) -> set[str]:
    return _tokenize(
        " ".join(
            part
            for part in (
                citation.source_provider,
                citation.source_id,
                citation.title or "",
                citation.origin_url or "",
                citation.url or "",
            )
            if part
        )
    )


def _named_tokens(value: str) -> set[str]:
    return {token.lower() for token in _NAMED_TOKEN_PATTERN.findall(str(value))}


def _determine_verdict(
    *,
    citation_indices: list[int],
    related_gap_indices: list[int],
    uncovered_named_tokens: list[str],
) -> str:
    if len(citation_indices) >= 2 and not related_gap_indices and not uncovered_named_tokens:
        return "supported"
    if citation_indices:
        return "contested"
    return "insufficient"


def _conflict_reason(
    *,
    citation_indices: list[int],
    related_gap_indices: list[int],
    uncovered_named_tokens: list[str],
) -> str:
    if related_gap_indices:
        return "coverage_gap"
    if citation_indices and uncovered_named_tokens:
        return "partial_support"
    return "insufficient_evidence"
