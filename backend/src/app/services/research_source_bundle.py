"""Research source bundle 收口与去重。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from app.schemas.research import ResearchCanonicalCitation, ResearchSourceTarget, ResearchSourceType


@dataclass(slots=True, frozen=True)
class ResearchSourceBundle:
    target_sources: tuple[ResearchSourceTarget, ...]
    citations: list[ResearchCanonicalCitation]
    findings: list[str]
    interim_summary: str
    coverage_gaps: list[str]
    provider_counts: dict[str, int]


class ResearchSourceBundleBuilder:
    """把多 provider 证据收口成可恢复、可 finalizer 消费的 source bundle。"""

    def build(
        self,
        *,
        target_sources: Sequence[ResearchSourceTarget],
        citations: Sequence[ResearchCanonicalCitation],
        findings: Sequence[str],
        required_web_providers: Sequence[str] = (),
    ) -> ResearchSourceBundle:
        normalized_required_web_providers = tuple(
            dict.fromkeys(
                str(provider).strip()
                for provider in required_web_providers
                if str(provider).strip()
            )
        )
        normalized_citations = [
            self._normalize_citation(citation)
            for citation in citations
        ]
        deduped = self._dedupe_citations(normalized_citations)
        provider_counts = Counter(citation.source_provider for citation in normalized_citations)
        coverage_gaps = [
            f"缺少 provider 证据：{provider}"
            for provider in normalized_required_web_providers
            if provider not in provider_counts
        ]
        interim_summary = (
            f"已汇总 {len(deduped)} 条去重证据，"
            f"覆盖 provider：{', '.join(sorted(provider_counts)) or 'none'}。"
        )
        return ResearchSourceBundle(
            target_sources=tuple(target_sources),
            citations=deduped,
            findings=[item.strip() for item in findings if str(item).strip()],
            interim_summary=interim_summary,
            coverage_gaps=coverage_gaps,
            provider_counts=dict(provider_counts),
        )

    @staticmethod
    def _dedupe_citations(
        citations: Sequence[ResearchCanonicalCitation],
    ) -> list[ResearchCanonicalCitation]:
        deduped: list[ResearchCanonicalCitation] = []
        seen_keys: set[tuple[str, str]] = set()
        for citation in citations:
            key = ResearchSourceBundleBuilder._dedupe_key(citation)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(citation)
        return deduped

    @staticmethod
    def _normalize_citation(
        citation: ResearchCanonicalCitation,
    ) -> ResearchCanonicalCitation:
        if citation.source_type == ResearchSourceType.WEB and citation.origin_url:
            return citation.model_copy(update={"url": citation.origin_url})
        return citation

    @staticmethod
    def _dedupe_key(citation: ResearchCanonicalCitation) -> tuple[str, str]:
        if citation.source_type == ResearchSourceType.WEB:
            return (
                citation.source_type.value,
                str(citation.origin_url or citation.url or citation.source_id),
            )
        if citation.source_type == ResearchSourceType.PAPER:
            return (
                citation.source_type.value,
                str(citation.arxiv_id or citation.source_id),
            )
        return (citation.source_type.value, str(citation.source_id))
