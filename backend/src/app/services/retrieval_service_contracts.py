from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import uuid

QUERY_FANOUT_CONCURRENCY = 3
DEDUP_EMBEDDING_SIMILARITY_THRESHOLD = 0.95
DEFAULT_RESULT_EXCERPT_MAX_CHARS = 500
EXPANDED_RESULT_EXCERPT_MAX_CHARS = 4000


@dataclass(slots=True)
class RetrievedChunk:
    id: uuid.UUID
    kb_id: uuid.UUID
    material_id: uuid.UUID
    content: str
    context: str | None
    locator: dict | None
    metadata: dict | None
    chunk_role: str | None
    parent_chunk_id: str | None
    child_seq: int | None
    chunk_index: int | None = None
    heading_path: str | None = None
    global_chunk_order: int | None = None


@dataclass(slots=True)
class RetrievalResult:
    chunk: RetrievedChunk
    score: float
    context_text: str | None = None


@dataclass(slots=True)
class RetrievalStats:
    query: str
    normalized_query: str
    effective_query: str
    top_k: int
    min_score: float | None
    total_hits: int
    filtered_count: int
    returned_count: int
    cache_hit: bool = False
    rewrite_enabled: bool = False
    rewrite_applied: bool = False
    rewrite_reason: str | None = None
    rewrite_latency_ms: int | None = None
    hybrid_enabled: bool = False
    rerank_enabled: bool = False
    rerank_applied: bool = False
    rerank_reason: str | None = None
    rerank_latency_ms: int | None = None
    reason: str | None = None


@dataclass(slots=True)
class RetrievalFeatureFlags:
    query_rewrite_enabled: bool
    hybrid_enabled: bool
    rerank_enabled: bool


@dataclass(slots=True)
class RetrievalRuntimeOverrides:
    hybrid_rrf_k: int
    retrieval_top_k: int
    retrieval_rerank_top_k: int
    parent_max_parents: int
    parent_max_children_per_parent: int
    multiscale_per_window_top_k: int
    multiscale_rrf_k: int
    multiscale_max_documents: int
    multiscale_max_chunks_per_document: int


@dataclass(slots=True)
class RetrievalLayerDraft:
    """统一检索层输出，兼容 agentic state 与旧工具接口。

    - retrieval_candidates: RRF-fused (global) candidates after caps, before rerank
    - reranked_candidates: rerank output capped to Top-N (or RRF Top-N fallback)
    - evidence_items: evidence draft for Top-N (chunk-level, with provenance)
    - results: final RetrievalResult list for legacy callers (Top-N)
    """

    retrieval_candidates: list[dict]
    reranked_candidates: list[dict]
    evidence_items: list[dict]
    results: list[RetrievalResult]
    stats: dict[str, object]


class RetrievalServiceProtocol(Protocol):
    _db: Any
    _milvus: Any
    _embedding: Any
    _redis: Any
    _query_rewriter: Any
    _reranker: Any
    _settings: Any
    _last_stats: RetrievalStats | None
    _last_layer_draft: RetrievalLayerDraft | None

    @staticmethod
    def _make_deadline(timeout_seconds: float | None) -> float | None: ...

    @staticmethod
    def _remaining_seconds(deadline: float | None) -> float | None: ...

    @staticmethod
    def _int_from_object(value: object, default: int = 0) -> int: ...

    @staticmethod
    def _effective_timeout(
        *,
        deadline: float | None,
        per_call_timeout: float | None,
    ) -> float | None: ...

    @staticmethod
    async def _run_with_timeout(coro: Any, timeout_seconds: float | None) -> Any: ...

    async def _db_execute(self, stmt: Any) -> Any: ...

    @staticmethod
    def _empty_layer_draft(reason: str | None = None) -> RetrievalLayerDraft: ...

    @staticmethod
    def _candidate_key(chunk: RetrievedChunk) -> tuple[str, str, str]: ...

    def _cache_key(
        self,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int,
        strategy: dict[str, object],
    ) -> str: ...

    def _strategy_fingerprint(
        self,
        top_k: int,
        *,
        feature_flags: RetrievalFeatureFlags,
        runtime_overrides: RetrievalRuntimeOverrides,
        kb_fingerprint: dict[str, dict[str, object]] | None = None,
    ) -> dict[str, object]: ...

    def _normalize_query(self, query: str) -> str: ...

    def _resolve_feature_flags(
        self,
        feature_overrides: dict[str, object] | None,
    ) -> RetrievalFeatureFlags: ...

    def _resolve_runtime_overrides(
        self,
        feature_overrides: dict[str, object] | None,
    ) -> RetrievalRuntimeOverrides: ...

    async def _load_kb_index_configs(self, kb_ids: list[uuid.UUID]) -> Any: ...

    def _build_kb_fingerprint(self, configs: Any) -> dict[str, dict[str, object]]: ...

    def _split_kb_ids_by_strategy(
        self,
        kb_ids: list[uuid.UUID],
        configs: Any,
    ) -> tuple[list[str], list[str]]: ...

    def _build_multiscale_window_collections(
        self,
        configs: Any,
        *,
        base_collection: str,
    ) -> list[str]: ...

    async def _maybe_rewrite_query(self, query: str, *, enabled: bool = True) -> Any: ...

    async def _resolve_query_embedding(
        self,
        item: Any,
        *,
        timeout_seconds: float | None = None,
        optional: bool = False,
    ) -> Any: ...

    @staticmethod
    def _embedding_failure_reason(
        exc: Exception,
        *,
        fallback_stage: str,
    ) -> str: ...

    @staticmethod
    def _query_embedding_stage(item: Any) -> str: ...

    @staticmethod
    def _query_hit_source(item: Any) -> Any: ...

    @staticmethod
    def _add_hit_source(hits: Any, src: Any) -> None: ...

    @staticmethod
    def _rrf_rank(ranked_lists: Any, *, k: int) -> Any: ...

    @staticmethod
    def _build_chunk_from_hit(hit: Any) -> RetrievedChunk | None: ...

    @staticmethod
    def _build_chunk_from_record(record: dict[str, Any]) -> RetrievedChunk | None: ...

    async def _hydrate_chunks_from_postgres(self, chunks: list[RetrievedChunk]) -> None: ...

    async def _expand_direct_section_neighbors(
        self,
        results: list[RetrievalResult],
        *,
        query_items: Any,
        top_n: int,
        timeout_seconds: float | None = None,
        hits_by_key: Any = None,
    ) -> list[RetrievalResult]: ...

    async def _apply_parent_child_strategy(
        self,
        results: list[RetrievalResult],
        kb_configs: Any,
        *,
        max_parents: int,
        max_children_per_parent: int,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]: ...

    async def _apply_query_dependent_multiscale_strategy(
        self,
        results: list[RetrievalResult],
        kb_configs: Any,
        *,
        per_window_top_k: int,
        rrf_k: int,
        max_documents: int,
        max_chunks_per_document: int,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]: ...

    async def _ensure_chunk_citation_labels(self, chunks: list[RetrievedChunk]) -> None: ...

    async def _maybe_rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int,
        *,
        timeout_seconds: float | None = None,
        hard_timeout: bool = False,
        enabled: bool | None = None,
    ) -> tuple[list[RetrievalResult], bool, str | None, int | None]: ...

    async def _populate_result_context_from_heading_path(
        self,
        result: RetrievalResult,
        *,
        timeout_seconds: float | None = None,
        scan_radius: int = 8,
    ) -> RetrievalResult: ...

    def _apply_stage_score_cutoff(
        self,
        results: list[RetrievalResult],
        *,
        stage: Any,
    ) -> tuple[list[RetrievalResult], int]: ...

    def _dedupe_by_chunk_identity(
        self,
        results: list[RetrievalResult],
    ) -> tuple[list[RetrievalResult], int]: ...

    def _dedupe_by_content_hash(
        self,
        results: list[RetrievalResult],
    ) -> tuple[list[RetrievalResult], int]: ...

    async def _dedupe_by_semantic_similarity(
        self,
        candidates: list[RetrievalResult],
        *,
        similarity_threshold: float,
        timeout_seconds: float | None = None,
    ) -> tuple[list[RetrievalResult], int, str]: ...

    def _result_text(self, result: RetrievalResult) -> str: ...

    def _result_excerpt(self, result: RetrievalResult) -> str: ...

    async def retrieve_layer(
        self,
        *,
        query_items: Any,
        kb_ids: list[uuid.UUID],
        top_n: int,
        per_query_top_k: int | None = None,
        global_candidates_limit: int | None = None,
        rerank_input_limit: int | None = None,
        extra_filter_expr: str | None = None,
        timeout_seconds: float | None = None,
        feature_overrides: dict[str, object] | None = None,
    ) -> RetrievalLayerDraft: ...