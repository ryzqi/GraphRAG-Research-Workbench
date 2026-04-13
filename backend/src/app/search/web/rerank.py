"""融合后重排。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from langchain_core.documents import Document

from app.config.policy_loader import load_search_policy
from app.config.policy_models import SearchRerankPolicy

from .documents import extract_domain, merge_document_metadata


def _extract_query_terms(query: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[\w-]+", str(query or "").lower())
        if len(term) >= 2
    }


def _score_document(
    document: Document,
    *,
    query_terms: set[str],
    rerank_policy: SearchRerankPolicy,
) -> float:
    metadata = document.metadata
    fusion_score = float(metadata.get("fusion_score") or 0.0)
    overlap_bonus = float(rerank_policy.overlap_bonus_weight) * max(
        int(metadata.get("overlap_count") or 1) - 1,
        0,
    )
    searchable = f"{metadata.get('title') or ''} {document.page_content or ''}".lower()
    lexical_bonus = sum(
        float(rerank_policy.lexical_bonus_per_term)
        for term in query_terms
        if term in searchable
    )
    domain = str(
        metadata.get("domain") or extract_domain(str(metadata.get("url") or "")) or ""
    )
    authority_bonus = (
        float(rerank_policy.authority_bonus)
        if any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in rerank_policy.high_authority_domain_suffixes
        )
        else 0.0
    )
    freshness_bonus = (
        float(rerank_policy.freshness_bonus) if metadata.get("published_at") else 0.0
    )
    social_penalty = (
        float(rerank_policy.social_penalty)
        if any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in rerank_policy.low_quality_domain_suffixes
        )
        else 0.0
    )
    enriched_bonus = (
        float(rerank_policy.enriched_bonus) if metadata.get("enriched") else 0.0
    )
    return (
        fusion_score
        + overlap_bonus
        + lexical_bonus
        + authority_bonus
        + freshness_bonus
        + enriched_bonus
        - social_penalty
    )


def rerank_documents(
    documents: Sequence[Document], *, query: str, max_results: int
) -> list[Document]:
    query_terms = _extract_query_terms(query)
    rerank_policy = load_search_policy().rerank
    ranked = sorted(
        documents,
        key=lambda document: _score_document(
            document,
            query_terms=query_terms,
            rerank_policy=rerank_policy,
        ),
        reverse=True,
    )
    output: list[Document] = []
    for document in ranked[: max(max_results, 0)]:
        output.append(
            merge_document_metadata(
                document,
                fusion_score=_score_document(
                    document,
                    query_terms=query_terms,
                    rerank_policy=rerank_policy,
                ),
            )
        )
    return output
