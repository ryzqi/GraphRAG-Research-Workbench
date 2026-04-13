"""多 retriever 结果融合。"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping

from langchain_core.documents import Document

from app.config.policy_loader import load_search_policy

from .documents import canonicalize_url, document_url, merge_document_metadata


def _document_priority(
    document: Document,
    *,
    provider_weights: Mapping[str, float],
) -> tuple[float, float, int]:
    provider = str(document.metadata.get("provider") or "").strip()
    provider_rank = int(document.metadata.get("provider_rank") or 10**6)
    snippet_length = len(str(document.page_content or "").strip())
    return (
        float(provider_weights.get(provider, 1.0)),
        -provider_rank,
        snippet_length,
    )


def fuse_documents(
    groups: Iterable[list[Document]], *, max_results: int
) -> list[Document]:
    fusion_policy = load_search_policy().fusion
    provider_weights = fusion_policy.provider_weights
    rrf_k = int(fusion_policy.rrf_k)
    unique_docs: dict[str, Document] = {}
    fusion_scores: dict[str, float] = defaultdict(float)
    overlap_counts: Counter[str] = Counter()
    first_seen_order: list[str] = []

    for documents in groups:
        for rank, document in enumerate(documents, start=1):
            provider = str(document.metadata.get("provider") or "").strip()
            canonical_url = canonicalize_url(document_url(document))
            if not canonical_url:
                continue
            weight = float(provider_weights.get(provider, 1.0))
            fusion_scores[canonical_url] += weight / (rank + rrf_k)
            overlap_counts[canonical_url] += 1
            existing = unique_docs.get(canonical_url)
            if existing is None:
                unique_docs[canonical_url] = document
                first_seen_order.append(canonical_url)
                continue
            if _document_priority(
                document,
                provider_weights=provider_weights,
            ) > _document_priority(
                existing,
                provider_weights=provider_weights,
            ):
                unique_docs[canonical_url] = merge_document_metadata(
                    document,
                    fusion_score=float(fusion_scores[canonical_url]),
                    overlap_count=int(overlap_counts[canonical_url]),
                )

    ranked = sorted(
        first_seen_order,
        key=lambda key: (
            float(fusion_scores[key]),
            int(overlap_counts[key]),
            len(str(unique_docs[key].page_content or "").strip()),
        ),
        reverse=True,
    )

    output: list[Document] = []
    for key in ranked[: max(max_results, 0)]:
        output.append(
            merge_document_metadata(
                unique_docs[key],
                fusion_score=float(fusion_scores[key]),
                overlap_count=int(overlap_counts[key]),
            )
        )
    return output
