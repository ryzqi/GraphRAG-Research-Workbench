"""融合后重排。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from langchain_core.documents import Document

from .documents import extract_domain, merge_document_metadata

_LOW_QUALITY_DOMAIN_SUFFIXES = (
    "linkedin.com",
    "x.com",
    "twitter.com",
    "medium.com",
)
_HIGH_AUTHORITY_DOMAIN_SUFFIXES = (
    "docs.langchain.com",
    "openai.com",
    "help.openai.com",
    "docs.anthropic.com",
    "ai.google.dev",
    "learn.microsoft.com",
)


def _extract_query_terms(query: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[\w-]+", str(query or "").lower())
        if len(term) >= 2
    }


def _score_document(document: Document, *, query_terms: set[str]) -> float:
    metadata = document.metadata
    fusion_score = float(metadata.get("fusion_score") or 0.0)
    overlap_bonus = 0.9 * max(int(metadata.get("overlap_count") or 1) - 1, 0)
    searchable = f"{metadata.get('title') or ''} {document.page_content or ''}".lower()
    lexical_bonus = sum(0.08 for term in query_terms if term in searchable)
    domain = str(
        metadata.get("domain") or extract_domain(str(metadata.get("url") or "")) or ""
    )
    authority_bonus = (
        0.45
        if any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in _HIGH_AUTHORITY_DOMAIN_SUFFIXES
        )
        else 0.0
    )
    freshness_bonus = 0.12 if metadata.get("published_at") else 0.0
    social_penalty = (
        0.35
        if any(
            domain == suffix or domain.endswith(f".{suffix}")
            for suffix in _LOW_QUALITY_DOMAIN_SUFFIXES
        )
        else 0.0
    )
    enriched_bonus = 0.15 if metadata.get("enriched") else 0.0
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
    ranked = sorted(
        documents,
        key=lambda document: _score_document(document, query_terms=query_terms),
        reverse=True,
    )
    output: list[Document] = []
    for document in ranked[: max(max_results, 0)]:
        output.append(
            merge_document_metadata(
                document,
                fusion_score=_score_document(document, query_terms=query_terms),
            )
        )
    return output
