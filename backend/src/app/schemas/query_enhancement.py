"""Query enhancement / provenance types (JSON-friendly).

These structures are shared between agentic graph state and services.
Keep them serializable (plain dict/list/str/bool/int) so LangGraph checkpointing
can persist them safely.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# NOTE: Keep in sync with KB agentic state and retrieval provenance needs.
QuerySourceKind = Literal[
    # Main question after preprocessing.
    "main",
    # Decomposition sub-question.
    "subquery",
    # Multi-query variant.
    "variant",
    # HyDE synthetic query/document.
    "hyde",
    # Any rewrite/transform invoked during retries.
    "rewrite",
    # Fallback / unknown source.
    "other",
]


class QueryRef(TypedDict, total=False):
    """A reference to a query used in retrieval / scoring provenance."""

    kind: QuerySourceKind
    query: str
    # For subquery/variant, record the 0-based index in the corresponding list.
    index: int
    note: str


# Provenance attached to candidates/evidence.
QueryHitSource = QueryRef


class QueryItem(QueryRef, total=False):
    """A concrete query input used by the retrieval layer.

    use_dense/use_bm25 allow HyDE or other strategies to affect only one path.
    """

    origin: str
    subquery_id: str
    priority: int
    coverage_tags: list[str]
    purpose: str
    quality_score: float
    use_dense: bool
    use_bm25: bool
    # Optional batched HyDE payload. Keep `query` as the primary/preview item.
    hyde_queries: list[str]
    hyde_aggregation: Literal["mean_embedding"]
