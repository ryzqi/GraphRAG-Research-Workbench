"""检索服务：Milvus 召回（Milvus-only）+ 可配置缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.redis_client import RedisClient
from app.integrations.rerank_client import RerankClient
from app.models.document_chunk import DocumentChunk
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.schemas.chats import EvidenceItem, EvidenceSourceKind
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.schemas.query_enhancement import QueryHitSource, QueryItem
from app.services.query_dependent_collections import collection_name_for_window
from app.services.query_rewrite_service import (
    QueryRewriteService,
    RewriteResult,
    build_query_items,
)

logger = logging.getLogger(__name__)


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
    hybrid_ranker: str | None = None
    rerank_enabled: bool = False
    rerank_applied: bool = False
    rerank_reason: str | None = None
    rerank_latency_ms: int | None = None
    reason: str | None = None


@dataclass(slots=True)
class RetrievalLayerDraft:
    """Unified retrieval layer output (for agentic state + legacy tool compatibility).

    - retrieval_candidates: RRF-fused (global) candidates after caps, before rerank
    - reranked_candidates: rerank output capped to Top-N (or RRF Top-N fallback)
    - evidence_items: evidence draft for Top-N (chunk-level, with provenance)
    - results: final RetrievalResult list for legacy callers (Top-N)
    """

    retrieval_candidates: list[dict]
    reranked_candidates: list[dict]
    evidence_items: list[dict]
    results: list["RetrievalResult"]
    stats: dict[str, object]


class RetrievalService:
    def __init__(
        self,
        db: AsyncSession,
        milvus: MilvusClient,
        embedding: EmbeddingClient,
        redis: RedisClient | None = None,
        query_rewriter: QueryRewriteService | None = None,
        reranker: RerankClient | None = None,
    ) -> None:
        self._db = db
        self._milvus = milvus
        self._embedding = embedding
        self._redis = redis
        self._query_rewriter = query_rewriter
        self._reranker = reranker
        self._settings = get_settings()
        self._last_stats: RetrievalStats | None = None
        self._last_layer_draft: RetrievalLayerDraft | None = None

    @property
    def last_stats(self) -> RetrievalStats | None:
        return self._last_stats

    @property
    def last_layer_draft(self) -> RetrievalLayerDraft | None:
        """Last unified retrieval layer draft for the most recent retrieval call."""
        return self._last_layer_draft

    @staticmethod
    def _make_deadline(timeout_seconds: float | None) -> float | None:
        if timeout_seconds is None:
            return None
        return time.monotonic() + max(float(timeout_seconds), 0.0)

    @staticmethod
    def _remaining_seconds(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    @staticmethod
    def _effective_timeout(
        *,
        deadline: float | None,
        per_call_timeout: float | None,
    ) -> float | None:
        remaining = RetrievalService._remaining_seconds(deadline)
        if remaining is None:
            return per_call_timeout
        if per_call_timeout is None:
            return remaining
        return max(0.0, min(float(per_call_timeout), remaining))

    @staticmethod
    async def _run_with_timeout(coro, timeout_seconds: float | None):
        if timeout_seconds is None:
            return await coro
        if timeout_seconds <= 0:
            raise asyncio.TimeoutError()
        return await asyncio.wait_for(coro, timeout=timeout_seconds)

    @staticmethod
    def _empty_layer_draft(reason: str | None = None) -> RetrievalLayerDraft:
        stats: dict[str, object] = {
            "dense_hits": 0,
            "bm25_hits": 0,
            "rrf_candidates": 0,
            "rerank_applied": False,
        }
        if reason:
            stats["reason"] = reason
        return RetrievalLayerDraft(
            retrieval_candidates=[],
            reranked_candidates=[],
            evidence_items=[],
            results=[],
            stats=stats,
        )

    async def _hydrate_chunks_from_postgres(self, chunks: list[RetrievedChunk]) -> None:
        """Backfill chunk fields when Milvus hits lack output_fields.

        Prefer Milvus output_fields; only query Postgres when fields are missing.
        """

        if not chunks or self._db is None:
            return

        missing: set[uuid.UUID] = set()
        for c in chunks:
            missing_content = not c.content
            missing_locator = c.locator is None or c.locator == {}
            if missing_content or missing_locator:
                missing.add(c.id)
        if not missing:
            return

        stmt = select(
            DocumentChunk.id, DocumentChunk.raw_text, DocumentChunk.locator
        ).where(DocumentChunk.id.in_(list(missing)))
        result = await self._db.execute(stmt)
        by_id: dict[uuid.UUID, tuple[str, dict | None]] = {
            row.id: (row.raw_text, row.locator) for row in result.all()
        }
        for c in chunks:
            got = by_id.get(c.id)
            if not got:
                continue
            text, locator = got
            if not c.content:
                c.content = text or ""
            if (c.locator is None or c.locator == {}) and locator:
                c.locator = locator

    def _cache_key(
        self, query: str, kb_ids: list[uuid.UUID], top_k: int, strategy: dict
    ) -> str:
        """生成缓存键。"""
        kb_str = ",".join(sorted(str(k) for k in kb_ids))
        fingerprint = json.dumps(strategy, sort_keys=True, ensure_ascii=False)
        raw = f"retrieval:{query}:{kb_str}:{top_k}:{fingerprint}"
        return f"retrieval:{hashlib.md5(raw.encode()).hexdigest()}"

    def _embedding_cache_key(self, query: str) -> str:
        """生成 embedding 缓存键。"""
        return f"embedding:{hashlib.md5(query.encode()).hexdigest()}"

    def _rewrite_cache_key(self, query: str) -> str:
        """生成 query rewrite 缓存键。"""
        return f"rewrite:{hashlib.md5(query.encode()).hexdigest()}"

    def _strategy_fingerprint(
        self, top_k: int, kb_fingerprint: dict[str, dict] | None = None
    ) -> dict:
        """生成策略指纹，避免配置变更误命中缓存。"""
        fingerprint = {
            "top_k": top_k,
            "min_score": self._settings.retrieval_min_score,
            "hybrid_enabled": self._settings.retrieval_hybrid_enabled,
            "hybrid_ranker": self._settings.retrieval_hybrid_ranker,
            "hybrid_dense_weight": self._settings.retrieval_hybrid_dense_weight,
            "hybrid_sparse_weight": self._settings.retrieval_hybrid_sparse_weight,
            "hybrid_rrf_k": self._settings.retrieval_hybrid_rrf_k,
            "rewrite_enabled": self._settings.retrieval_query_rewrite_enabled,
            "rerank_enabled": self._settings.retrieval_rerank_enabled,
            "rerank_model": self._settings.retrieval_rerank_model,
            "embedding_model": self._settings.embedding_model,
        }
        if kb_fingerprint:
            fingerprint["kb_retrieval"] = kb_fingerprint
        return fingerprint

    def _normalize_query(self, query: str) -> str:
        """规范化 query，用于缓存一致性。"""
        normalized = " ".join(query.strip().split())
        if self._settings.retrieval_query_lowercase:
            normalized = normalized.lower()
        return normalized

    async def _get_query_embedding(
        self, query: str, *, timeout_seconds: float | None = None
    ) -> list[float]:
        """获取查询向量（带缓存）。"""
        if self._redis and self._settings.retrieval_cache_enabled:
            cache_key = self._embedding_cache_key(query)
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding 缓存读取失败，跳过缓存", extra={"error": str(exc)}
                )
                cached = None
            if cached:
                logger.debug("Embedding 缓存命中", extra={"query": query[:50]})
                return json.loads(cached)

        timeout_value = float(self._settings.embedding_timeout_seconds)
        if timeout_seconds is not None:
            timeout_value = min(timeout_value, float(timeout_seconds))
        if timeout_value <= 0:
            raise asyncio.TimeoutError()

        start_time = time.perf_counter()
        embeddings = await self._run_with_timeout(
            self._embedding.embed(texts=[query]), timeout_value
        )
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "Embedding 生成完成",
            extra={"query": query[:50], "latency_ms": latency_ms},
        )

        # 缓存 embedding（TTL 较长，因为相同文本的 embedding 不变）
        if self._redis and self._settings.retrieval_cache_enabled:
            try:
                await self._redis.set(
                    self._embedding_cache_key(query),
                    json.dumps(embeddings[0]),
                    ex=self._settings.retrieval_cache_ttl_seconds * 2,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Embedding 缓存写入失败，跳过缓存", extra={"error": str(exc)}
                )

        return embeddings[0]

    async def _maybe_rewrite_query(
        self, query: str, *, timeout_seconds: float | None = None
    ) -> RewriteResult:
        """可选查询重写，失败回退原 query。"""
        if not self._settings.retrieval_query_rewrite_enabled:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="disabled",
                latency_ms=0,
            )
        if timeout_seconds is not None and float(timeout_seconds) <= 0:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="budget_exhausted",
                latency_ms=0,
            )

        cache_key = self._rewrite_cache_key(query)
        if self._redis and self._settings.retrieval_cache_enabled:
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Rewrite �����ȡʧ�ܣ���������", extra={"error": str(exc)}
                )
                cached = None
            if cached:
                return RewriteResult(
                    query=cached,
                    rewritten=cached.strip() != query,
                    reason="cache_hit",
                    latency_ms=0,
                )

        rewriter = self._query_rewriter or QueryRewriteService(self._settings)
        self._query_rewriter = rewriter
        result = await rewriter.rewrite(query, timeout_seconds=timeout_seconds)

        if self._redis and self._settings.retrieval_cache_enabled and result.query:
            try:
                await self._redis.set(
                    cache_key,
                    result.query,
                    ex=self._settings.retrieval_cache_ttl_seconds,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Rewrite 缓存写入失败，跳过缓存", extra={"error": str(exc)}
                )

        return result

    @staticmethod
    def _candidate_key(chunk: RetrievedChunk) -> tuple[str, str, str]:
        # Keep a stable, explicit key for global dedupe across KBs/materials.
        return (str(chunk.kb_id), str(chunk.material_id), str(chunk.id))

    @staticmethod
    def _query_hit_source(item: QueryItem) -> QueryHitSource:
        src: QueryHitSource = {
            "kind": item.get("kind", "other"),  # type: ignore[typeddict-item]
            "query": item.get("query", ""),  # type: ignore[typeddict-item]
        }
        if "index" in item:
            src["index"] = int(item["index"])  # type: ignore[typeddict-item]
        if "note" in item and item.get("note"):
            src["note"] = str(item["note"])  # type: ignore[typeddict-item]
        return src

    @staticmethod
    def _add_hit_source(hits: list[QueryHitSource], src: QueryHitSource) -> None:
        key = (src.get("kind"), src.get("query"), src.get("index"), src.get("note"))
        for existing in hits:
            ek = (
                existing.get("kind"),
                existing.get("query"),
                existing.get("index"),
                existing.get("note"),
            )
            if ek == key:
                return
        hits.append(src)

    @staticmethod
    def _rrf_rank(
        ranked_lists: list[list[tuple[str, str, str]]],
        *,
        k: int,
    ) -> tuple[list[tuple[str, str, str]], dict[tuple[str, str, str], float]]:
        """Reciprocal Rank Fusion (RRF).

        Returns (ordered_keys, score_by_key).
        """

        scores: dict[tuple[str, str, str], float] = {}
        best_rank: dict[tuple[str, str, str], int] = {}
        for lst in ranked_lists:
            for rank, key in enumerate(lst, start=1):
                scores[key] = scores.get(key, 0.0) + 1.0 / float(k + rank)
                best_rank[key] = min(best_rank.get(key, rank), rank)

        ordered = sorted(
            scores.keys(),
            key=lambda key: (-scores[key], best_rank.get(key, 10**9), key),
        )
        return ordered, scores

    @staticmethod
    def _build_multiscale_window_collections(
        configs: dict[uuid.UUID, IndexConfig],
        *,
        base_collection: str,
    ) -> list[str]:
        names: set[str] = set()
        for cfg in configs.values():
            if cfg.chunking.general_strategy != ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                continue
            for window in cfg.chunking.query_dependent_multiscale.windows:
                names.add(
                    collection_name_for_window(
                        base_collection,
                        window.chunk_size_tokens,
                        window.chunk_overlap_tokens,
                    )
                )
        return sorted(names)

    @staticmethod
    def _split_kb_ids_by_strategy(
        kb_ids: list[uuid.UUID],
        configs: dict[uuid.UUID, IndexConfig],
    ) -> tuple[list[str], list[str]]:
        default_kb_ids: list[str] = []
        multiscale_kb_ids: list[str] = []
        for kb_id in kb_ids:
            cfg = configs.get(kb_id)
            if cfg is None:
                default_kb_ids.append(str(kb_id))
                continue
            if cfg.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                multiscale_kb_ids.append(str(kb_id))
            else:
                default_kb_ids.append(str(kb_id))
        return default_kb_ids, multiscale_kb_ids

    async def retrieve_layer(
        self,
        *,
        query_items: list[QueryItem],
        kb_ids: list[uuid.UUID],
        top_n: int,
        per_query_top_k: int | None = None,
        global_candidates_limit: int | None = None,
        rerank_input_limit: int | None = None,
        extra_filter_expr: str | None = None,
        timeout_seconds: float | None = None,
    ) -> RetrievalLayerDraft:
        """Unified RetrievalLayer: dense + BM25 + global RRF + optional rerank + Top-N.

        NOTE: Any retry/transform query loop should come back to THIS method to ensure
        the retrieval chain stays consistent (dense+BM25+RRF+optional rerank).
        """

        deadline = self._make_deadline(timeout_seconds)
        if deadline is not None and float(timeout_seconds) <= 0:
            draft = self._empty_layer_draft(reason="timeout")
            self._last_layer_draft = draft
            return draft

        if not kb_ids or not query_items or top_n <= 0:
            draft = self._empty_layer_draft()
            self._last_layer_draft = draft
            return draft

        def _timeout_draft() -> RetrievalLayerDraft:
            draft = self._empty_layer_draft(reason="timeout")
            self._last_layer_draft = draft
            return draft

        # Enforce reasonable caps (production guardrails).
        top_n = min(int(top_n), int(self._settings.retrieval_max_top_k))
        per_query_top_k = (
            int(per_query_top_k) if per_query_top_k is not None else int(top_n)
        )
        per_query_top_k = max(
            1, min(per_query_top_k, int(self._settings.retrieval_max_top_k))
        )

        query_count = max(1, len(query_items))
        if global_candidates_limit is None:
            # Worst-case: dense+BM25 per query -> 2*per_query_top_k per query.
            global_candidates_limit = min(
                int(self._settings.retrieval_max_top_k),
                per_query_top_k * 2 * query_count,
            )
        global_candidates_limit = max(int(global_candidates_limit), top_n)
        global_candidates_limit = min(
            global_candidates_limit, int(self._settings.retrieval_max_top_k)
        )

        if rerank_input_limit is None:
            rerank_input_limit = global_candidates_limit
        rerank_input_limit = max(int(rerank_input_limit), top_n)
        rerank_input_limit = min(rerank_input_limit, global_candidates_limit)

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            kb_configs = await self._run_with_timeout(
                self._load_kb_index_configs(kb_ids), timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        default_kb_id_strs, multiscale_kb_id_strs = self._split_kb_ids_by_strategy(
            kb_ids, kb_configs
        )
        multiscale_collections = self._build_multiscale_window_collections(
            kb_configs,
            base_collection=self._settings.milvus_collection,
        )

        rrf_k = int(self._settings.retrieval_hybrid_rrf_k)

        chunk_by_key: dict[tuple[str, str, str], RetrievedChunk] = {}
        hits_by_key: dict[tuple[str, str, str], list[QueryHitSource]] = {}
        per_query_ranked: list[list[tuple[str, str, str]]] = []

        dense_hits_total = 0
        bm25_hits_total = 0

        # Use the "main" query as rerank query, fallback to the first available.
        main_query = ""
        for item in query_items:
            if item.get("kind") == "main" and (item.get("query") or "").strip():
                main_query = str(item.get("query") or "")
                break
        if not main_query:
            main_query = str(query_items[0].get("query") or "")

        for item in query_items:
            q = (item.get("query") or "").strip()
            if not q:
                continue
            if deadline is not None:
                remaining = self._remaining_seconds(deadline)
                if remaining is not None and remaining <= 0:
                    return _timeout_draft()

            use_dense = bool(item.get("use_dense", True))
            use_bm25 = bool(item.get("use_bm25", True)) and bool(
                self._settings.retrieval_hybrid_enabled
            )

            embedding: list[float] | None = None
            if use_dense:
                try:
                    remaining = self._remaining_seconds(deadline)
                    if remaining is not None and remaining <= 0:
                        return _timeout_draft()
                    embedding = await self._get_query_embedding(
                        q, timeout_seconds=remaining
                    )
                except asyncio.TimeoutError:
                    if deadline is not None:
                        return _timeout_draft()
                    logger.warning("Embedding 超时，跳过 dense", extra={"query": q[:50]})
                    embedding = None
                    use_dense = False
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        "Embedding 生成失败，跳过 dense", extra={"error": str(exc)}
                    )
                    embedding = None
                    use_dense = False

            async def _safe_dense():
                if not use_dense or embedding is None:
                    return []
                hits = []
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if default_kb_id_strs:
                        dense_default = await self._run_with_timeout(
                            self._milvus.search(
                                embedding=embedding,
                                kb_ids=default_kb_id_strs,
                                top_k=per_query_top_k,
                                extra_filter_expr=extra_filter_expr,
                            ),
                            timeout_value,
                        )
                        hits.extend(dense_default)

                    if multiscale_kb_id_strs:
                        for collection_name in multiscale_collections:
                            timeout_value = self._effective_timeout(
                                deadline=deadline, per_call_timeout=None
                            )
                            dense_window = await self._run_with_timeout(
                                self._milvus.search(
                                    embedding=embedding,
                                    kb_ids=multiscale_kb_id_strs,
                                    top_k=per_query_top_k,
                                    extra_filter_expr=extra_filter_expr,
                                    collection_name=collection_name,
                                ),
                                timeout_value,
                            )
                            hits.extend(dense_window)
                    return hits
                except asyncio.TimeoutError:
                    if deadline is not None:
                        raise
                    logger.warning("Dense 检索超时，降级为空", extra={"query": q[:50]})
                    return []
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Dense 检索失败，降级为空", extra={"error": str(exc)}
                    )
                    return []

            async def _safe_bm25():
                if not use_bm25:
                    return []
                hits = []
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if default_kb_id_strs:
                        bm25_default = await self._run_with_timeout(
                            self._milvus.bm25_search(
                                query=q,
                                kb_ids=default_kb_id_strs,
                                top_k=per_query_top_k,
                                extra_filter_expr=extra_filter_expr,
                            ),
                            timeout_value,
                        )
                        hits.extend(bm25_default)

                    if multiscale_kb_id_strs:
                        for collection_name in multiscale_collections:
                            timeout_value = self._effective_timeout(
                                deadline=deadline, per_call_timeout=None
                            )
                            bm25_window = await self._run_with_timeout(
                                self._milvus.bm25_search(
                                    query=q,
                                    kb_ids=multiscale_kb_id_strs,
                                    top_k=per_query_top_k,
                                    extra_filter_expr=extra_filter_expr,
                                    collection_name=collection_name,
                                ),
                                timeout_value,
                            )
                            hits.extend(bm25_window)
                    return hits
                except asyncio.TimeoutError:
                    if deadline is not None:
                        raise
                    logger.warning("BM25 检索超时，降级为空", extra={"query": q[:50]})
                    return []
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("BM25 检索失败，降级为空", extra={"error": str(exc)})
                    return []

            dense_hits = []
            bm25_hits = []
            if use_dense and use_bm25:
                if deadline is None:
                    async with asyncio.TaskGroup() as tg:
                        dense_task = tg.create_task(_safe_dense())
                        bm25_task = tg.create_task(_safe_bm25())
                    dense_hits = dense_task.result()
                    bm25_hits = bm25_task.result()
                else:
                    try:
                        dense_hits = await _safe_dense()
                        bm25_hits = await _safe_bm25()
                    except asyncio.TimeoutError:
                        return _timeout_draft()
            elif use_dense:
                try:
                    dense_hits = await _safe_dense()
                except asyncio.TimeoutError:
                    return _timeout_draft()
            elif use_bm25:
                try:
                    bm25_hits = await _safe_bm25()
                except asyncio.TimeoutError:
                    return _timeout_draft()

            dense_hits_total += len(dense_hits)
            bm25_hits_total += len(bm25_hits)

            src = self._query_hit_source(item)
            dense_keys: list[tuple[str, str, str]] = []
            bm25_keys: list[tuple[str, str, str]] = []

            for hit in dense_hits:
                chunk = self._build_chunk_from_hit(hit)
                if not chunk:
                    continue
                key = self._candidate_key(chunk)
                chunk_by_key.setdefault(key, chunk)
                hits_by_key.setdefault(key, [])
                self._add_hit_source(hits_by_key[key], src)
                dense_keys.append(key)

            for hit in bm25_hits:
                chunk = self._build_chunk_from_hit(hit)
                if not chunk:
                    continue
                key = self._candidate_key(chunk)
                chunk_by_key.setdefault(key, chunk)
                hits_by_key.setdefault(key, [])
                self._add_hit_source(hits_by_key[key], src)
                bm25_keys.append(key)

            # Defensive dedupe: ranked lists must not contain duplicates for RRF.
            if dense_keys:
                dense_keys = list(dict.fromkeys(dense_keys))
            if bm25_keys:
                bm25_keys = list(dict.fromkeys(bm25_keys))

            ranked_lists: list[list[tuple[str, str, str]]] = []
            if dense_keys:
                ranked_lists.append(dense_keys)
            if bm25_keys:
                ranked_lists.append(bm25_keys)

            if not ranked_lists:
                continue

            # Per-query fusion (dense + BM25) -> per-query ranked list.
            per_keys, _ = self._rrf_rank(ranked_lists, k=rrf_k)
            per_query_ranked.append(per_keys)

        if not per_query_ranked:
            draft = RetrievalLayerDraft(
                retrieval_candidates=[],
                reranked_candidates=[],
                evidence_items=[],
                results=[],
                stats={
                    "dense_hits": dense_hits_total,
                    "bm25_hits": bm25_hits_total,
                    "rrf_candidates": 0,
                    "rerank_applied": False,
                },
            )
            self._last_layer_draft = draft
            return draft

        global_keys, global_scores = self._rrf_rank(per_query_ranked, k=rrf_k)
        global_keys = global_keys[:global_candidates_limit]

        # Build RetrievalResult list in global RRF order.
        rrf_results: list[RetrievalResult] = []
        for key in global_keys:
            chunk = chunk_by_key.get(key)
            if chunk is None:
                continue
            rrf_results.append(
                RetrievalResult(chunk=chunk, score=global_scores.get(key, 0.0))
            )

        # Prefer Milvus output_fields; backfill from Postgres only when necessary.
        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            await self._run_with_timeout(
                self._hydrate_chunks_from_postgres([r.chunk for r in rrf_results]),
                timeout_value,
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        # kb_configs has been loaded before retrieval loop for multiscale routing.
        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            rrf_results = await self._apply_parent_child_strategy(
                rrf_results, kb_configs, timeout_seconds=timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            rrf_results = await self._apply_query_dependent_multiscale_strategy(
                rrf_results, kb_configs, timeout_seconds=timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_draft()

        pre_min_score_count = len(rrf_results)
        rrf_results, filtered_count = self._apply_min_score(rrf_results)

        # Rerank: RRF -> rerank -> Top-N. Inputs are additionally capped.
        rerank_applied = False
        rerank_reason: str | None = "disabled"
        rerank_latency_ms: int | None = None
        final_results: list[RetrievalResult] = []

        candidates_for_rerank = rrf_results[:rerank_input_limit]
        if candidates_for_rerank and self._settings.retrieval_rerank_enabled:
            try:
                rerank_timeout = self._effective_timeout(
                    deadline=deadline, per_call_timeout=timeout_seconds
                )
                ordered, applied, reason, latency_ms = await self._maybe_rerank(
                    main_query,
                    candidates_for_rerank,
                    top_n,
                    timeout_seconds=rerank_timeout,
                    hard_timeout=False,
                )
            except asyncio.TimeoutError:
                # Rerank is optional: degrade to RRF order when timeout happens.
                logger.warning("Rerank 超时，降级为 RRF 顺序")
                ordered, applied, reason, latency_ms = (
                    candidates_for_rerank,
                    False,
                    "timeout",
                    None,
                )
            rerank_applied = applied
            rerank_reason = reason
            rerank_latency_ms = latency_ms
            final_results = (ordered if applied else candidates_for_rerank)[:top_n]
        else:
            final_results = candidates_for_rerank[:top_n]

        # Build JSON-friendly drafts for agentic state / auditing.
        retrieval_candidates: list[dict] = []
        for r in rrf_results:
            key = self._candidate_key(r.chunk)
            retrieval_candidates.append(
                {
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "score": float(r.score),
                    "stage": "rrf",
                    "excerpt": (r.chunk.content or "")[:500],
                    "locator": r.chunk.locator,
                    "metadata": r.chunk.metadata,
                    "chunk_role": r.chunk.chunk_role,
                    "parent_chunk_id": r.chunk.parent_chunk_id,
                    "hits": hits_by_key.get(key, []),
                }
            )

        reranked_candidates: list[dict] = []
        for r in final_results:
            key = self._candidate_key(r.chunk)
            reranked_candidates.append(
                {
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "score": float(r.score),
                    "stage": "rerank" if rerank_applied else "rrf",
                    "excerpt": (r.chunk.content or "")[:500],
                    "locator": r.chunk.locator,
                    "metadata": r.chunk.metadata,
                    "chunk_role": r.chunk.chunk_role,
                    "parent_chunk_id": r.chunk.parent_chunk_id,
                    "hits": hits_by_key.get(key, []),
                }
            )

        evidence_items: list[dict] = []
        for r in final_results:
            key = self._candidate_key(r.chunk)
            evidence_items.append(
                {
                    "source_kind": "kb",
                    "kb_id": str(r.chunk.kb_id),
                    "material_id": str(r.chunk.material_id),
                    "chunk_id": str(r.chunk.id),
                    "locator": r.chunk.locator,
                    "excerpt": (r.chunk.content or "")[:500],
                    "score": float(r.score),
                    "hits": hits_by_key.get(key, []),
                }
            )

        draft = RetrievalLayerDraft(
            retrieval_candidates=retrieval_candidates,
            reranked_candidates=reranked_candidates,
            evidence_items=evidence_items,
            results=final_results,
            stats={
                "dense_hits": dense_hits_total,
                "bm25_hits": bm25_hits_total,
                "pre_min_score_candidates": pre_min_score_count,
                "filtered_count": filtered_count,
                "rrf_candidates": len(rrf_results),
                "global_candidates_limit": global_candidates_limit,
                "rerank_input_limit": rerank_input_limit,
                "rerank_applied": rerank_applied,
                "rerank_reason": rerank_reason,
                "rerank_latency_ms": rerank_latency_ms,
            },
        )
        self._last_layer_draft = draft
        return draft

    async def _maybe_rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int,
        *,
        timeout_seconds: float | None = None,
        hard_timeout: bool = False,
    ) -> tuple[list[RetrievalResult], bool, str | None, int | None]:
        """可选 rerank，失败回退原排序。"""
        if not self._settings.retrieval_rerank_enabled:
            return results, False, "disabled", None

        if not results:
            return results, False, "empty_candidates", None

        reranker = self._reranker or RerankClient(self._settings)
        self._reranker = reranker

        timeout_value = float(self._settings.retrieval_rerank_timeout_seconds)
        if timeout_seconds is not None:
            timeout_value = min(timeout_value, float(timeout_seconds))
        if timeout_value <= 0:
            return results, False, "budget_exhausted", None

        start_time = time.perf_counter()
        try:
            rerank_results = await self._run_with_timeout(
                reranker.rerank(
                    query=query,
                    documents=[r.chunk.content for r in results],
                    top_n=min(top_k, len(results)),
                    timeout_seconds=timeout_value,
                ),
                timeout_value,
            )
        except asyncio.TimeoutError:
            if hard_timeout:
                raise
            logger.warning("Rerank 超时，降级为原顺序", extra={"timeout": timeout_value})
            return results, False, "timeout", None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Rerank ����ʧ�ܣ�����ԭ����", extra={"error": str(exc)})
            return results, False, "error", None
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        if not rerank_results:
            return results, False, "empty_results", latency_ms

        ordered, used = [], set()
        for item in rerank_results:
            if 0 <= item.index < len(results):
                ordered.append(
                    RetrievalResult(chunk=results[item.index].chunk, score=item.score)
                )
                used.add(item.index)

        # 兜底保留未覆盖的候选
        for idx, res in enumerate(results):
            if idx not in used:
                ordered.append(res)

        return ordered, True, None, latency_ms

    async def _load_kb_index_configs(
        self, kb_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, IndexConfig]:
        if not kb_ids or self._db is None:
            return {}

        configs: dict[uuid.UUID, IndexConfig] = {}
        snapshot_stmt = select(KBConfigSnapshot.kb_id, KBConfigSnapshot.config_json).where(
            KBConfigSnapshot.kb_id.in_(kb_ids),
            KBConfigSnapshot.is_active.is_(True),
        )
        snapshot_rows = await self._db.execute(snapshot_stmt)
        for kb_id, raw in snapshot_rows.all():
            try:
                configs[kb_id] = IndexConfig.model_validate(raw or {})
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Snapshot IndexConfig 解析失败，回退 knowledge_bases",
                    extra={"kb_id": str(kb_id), "error": str(exc)},
                )

        missing_kb_ids = [kb_id for kb_id in kb_ids if kb_id not in configs]
        if missing_kb_ids:
            fallback_stmt = select(KnowledgeBase.id, KnowledgeBase.index_config).where(
                KnowledgeBase.id.in_(missing_kb_ids)
            )
            fallback_rows = await self._db.execute(fallback_stmt)
            for kb_id, raw in fallback_rows.all():
                try:
                    configs[kb_id] = IndexConfig.model_validate(raw or {})
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        "IndexConfig 解析失败，回退默认",
                        extra={"kb_id": str(kb_id), "error": str(exc)},
                    )
        return configs

    @staticmethod
    def _build_kb_fingerprint(configs: dict[uuid.UUID, IndexConfig]) -> dict[str, dict]:
        if not configs:
            return {}
        fingerprint: dict[str, dict] = {}
        for kb_id, cfg in configs.items():
            item = {
                "general_strategy": cfg.chunking.general_strategy.value,
                "parent_child": cfg.retrieval.parent_child.model_dump(mode="json"),
            }
            if cfg.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                item["query_dependent_multiscale"] = {
                    "windows": [
                        {
                            "chunk_size_tokens": window.chunk_size_tokens,
                            "chunk_overlap_tokens": window.chunk_overlap_tokens,
                        }
                        for window in cfg.chunking.query_dependent_multiscale.windows
                    ],
                    "retrieval": cfg.retrieval.query_dependent_multiscale.model_dump(
                        mode="json"
                    ),
                }
            fingerprint[str(kb_id)] = item
        return dict(sorted(fingerprint.items(), key=lambda item: item[0]))

    @staticmethod
    def _build_chunk_from_hit(hit) -> RetrievedChunk | None:
        chunk_id = getattr(hit, "chunk_id", None)
        kb_id = getattr(hit, "kb_id", None)
        material_id = getattr(hit, "material_id", None)
        if not chunk_id or not kb_id or not material_id:
            return None
        try:
            return RetrievedChunk(
                id=uuid.UUID(str(chunk_id)),
                kb_id=uuid.UUID(str(kb_id)),
                material_id=uuid.UUID(str(material_id)),
                content=getattr(hit, "content", "") or "",
                context=getattr(hit, "context", None),
                locator=getattr(hit, "locator", None),
                metadata=getattr(hit, "metadata", None),
                chunk_role=getattr(hit, "chunk_role", None),
                parent_chunk_id=getattr(hit, "parent_chunk_id", None),
                child_seq=getattr(hit, "child_seq", None),
            )
        except Exception:
            return None

    @staticmethod
    def _build_chunk_from_record(record: dict) -> RetrievedChunk | None:
        chunk_id = record.get("chunk_id")
        kb_id = record.get("kb_id")
        material_id = record.get("material_id")
        if not chunk_id or not kb_id or not material_id:
            return None
        try:
            return RetrievedChunk(
                id=uuid.UUID(str(chunk_id)),
                kb_id=uuid.UUID(str(kb_id)),
                material_id=uuid.UUID(str(material_id)),
                content=record.get("content") or "",
                context=record.get("context"),
                locator=record.get("locator"),
                metadata=record.get("metadata"),
                chunk_role=record.get("chunk_role"),
                parent_chunk_id=record.get("parent_chunk_id"),
                child_seq=record.get("child_seq"),
            )
        except Exception:
            return None

    async def _apply_parent_child_strategy(
        self,
        results: list[RetrievalResult],
        kb_configs: dict[uuid.UUID, IndexConfig],
        *,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        if not results or not kb_configs:
            for r in results:
                r.context_text = r.chunk.content
            return results
        if timeout_seconds is not None and float(timeout_seconds) <= 0:
            raise asyncio.TimeoutError()

        parent_ids: set[str] = set()
        selected_child_ids: set[uuid.UUID] = set()
        parent_child_kb_ids: set[uuid.UUID] = set()

        for kb_id, cfg in kb_configs.items():
            kb_results = [r for r in results if r.chunk.kb_id == kb_id]
            if not kb_results:
                continue

            if cfg.chunking.general_strategy != ChunkingStrategy.PARENT_CHILD:
                for r in kb_results:
                    r.context_text = r.chunk.content
                continue

            child_results = [
                r
                for r in kb_results
                if (r.chunk.chunk_role == "child" and r.chunk.parent_chunk_id)
            ]
            if not child_results:
                for r in kb_results:
                    r.context_text = r.chunk.content
                continue

            parent_child_kb_ids.add(kb_id)
            parent_scores: dict[str, float] = {}
            for r in child_results:
                parent_id = r.chunk.parent_chunk_id
                if not parent_id:
                    continue
                parent_scores[parent_id] = max(
                    parent_scores.get(parent_id, -1e9), r.score
                )

            max_parents = cfg.retrieval.parent_child.max_parents
            sorted_parents = sorted(
                parent_scores.items(), key=lambda item: item[1], reverse=True
            )[:max_parents]
            allowed_parents = {pid for pid, _ in sorted_parents}

            max_children = cfg.retrieval.parent_child.max_children_per_parent
            kept_children: dict[str, int] = {pid: 0 for pid in allowed_parents}
            for r in child_results:
                parent_id = r.chunk.parent_chunk_id
                if not parent_id or parent_id not in allowed_parents:
                    continue
                if kept_children[parent_id] >= max_children:
                    continue
                kept_children[parent_id] += 1
                selected_child_ids.add(r.chunk.id)

            parent_ids.update(allowed_parents)

        if not selected_child_ids:
            for r in results:
                if not r.context_text:
                    r.context_text = r.chunk.content
            return results

        parent_map: dict[str, RetrievedChunk] = {}
        if parent_ids:
            parent_records = await self._run_with_timeout(
                self._milvus.query_by_chunk_ids(chunk_ids=list(parent_ids)),
                timeout_seconds,
            )
            for record in parent_records:
                chunk = self._build_chunk_from_record(record)
                if chunk:
                    parent_map[str(chunk.id)] = chunk
            await self._run_with_timeout(
                self._hydrate_chunks_from_postgres(list(parent_map.values())),
                timeout_seconds,
            )

        for r in results:
            if r.chunk.id in selected_child_ids:
                parent = parent_map.get(r.chunk.parent_chunk_id or "")
                r.context_text = parent.content if parent else r.chunk.content
            elif r.context_text is None:
                r.context_text = r.chunk.content

        ordered: list[RetrievalResult] = []
        for r in results:
            if r.chunk.kb_id in parent_child_kb_ids:
                if r.chunk.id in selected_child_ids:
                    ordered.append(r)
            else:
                ordered.append(r)
        return ordered

    @staticmethod
    def _window_key_from_metadata(metadata: dict | None) -> tuple[int, int] | None:
        if not isinstance(metadata, dict):
            return None
        size = metadata.get("window_size_tokens")
        overlap = metadata.get("window_overlap_tokens")
        if not isinstance(size, int) or not isinstance(overlap, int):
            return None
        return size, overlap

    async def _apply_query_dependent_multiscale_strategy(
        self,
        results: list[RetrievalResult],
        kb_configs: dict[uuid.UUID, IndexConfig],
        *,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        if not results or not kb_configs:
            return results
        if timeout_seconds is not None and float(timeout_seconds) <= 0:
            raise asyncio.TimeoutError()

        multiscale_kb_ids = {
            kb_id
            for kb_id, cfg in kb_configs.items()
            if cfg.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
        }
        if not multiscale_kb_ids:
            return results

        selected_results: list[RetrievalResult] = []
        selected_chunk_ids: set[uuid.UUID] = set()

        for kb_id in multiscale_kb_ids:
            cfg = kb_configs.get(kb_id)
            if cfg is None:
                continue
            kb_results = [r for r in results if r.chunk.kb_id == kb_id]
            if not kb_results:
                continue

            by_window: dict[tuple[int, int], list[RetrievalResult]] = {}
            for item in kb_results:
                key = self._window_key_from_metadata(item.chunk.metadata)
                if key is None:
                    continue
                by_window.setdefault(key, []).append(item)

            if not by_window:
                continue

            ranked_doc_lists: list[list[tuple[str, str, str]]] = []
            per_window_top_k = cfg.retrieval.query_dependent_multiscale.per_window_top_k
            for window_items in by_window.values():
                ranked = sorted(window_items, key=lambda row: row.score, reverse=True)
                ranked = ranked[:per_window_top_k]

                seen_materials: set[str] = set()
                doc_list: list[tuple[str, str, str]] = []
                for row in ranked:
                    material_id = str(row.chunk.material_id)
                    if material_id in seen_materials:
                        continue
                    seen_materials.add(material_id)
                    doc_list.append((str(row.chunk.kb_id), material_id, "__doc__"))
                if doc_list:
                    ranked_doc_lists.append(doc_list)

            if not ranked_doc_lists:
                continue

            doc_rrf_keys, _ = self._rrf_rank(
                ranked_doc_lists,
                k=cfg.retrieval.query_dependent_multiscale.rrf_k,
            )
            max_documents = cfg.retrieval.query_dependent_multiscale.max_documents
            max_chunks_per_document = (
                cfg.retrieval.query_dependent_multiscale.max_chunks_per_document
            )
            ordered_material_ids = [key[1] for key in doc_rrf_keys[:max_documents]]

            for material_id in ordered_material_ids:
                material_chunks = [
                    row
                    for row in kb_results
                    if str(row.chunk.material_id) == material_id
                ]
                material_chunks = sorted(
                    material_chunks,
                    key=lambda row: row.score,
                    reverse=True,
                )[:max_chunks_per_document]
                for row in material_chunks:
                    if row.chunk.id in selected_chunk_ids:
                        continue
                    selected_chunk_ids.add(row.chunk.id)
                    if row.context_text is None:
                        row.context_text = row.chunk.content
                    selected_results.append(row)

        if not selected_results:
            return results

        fallback_results: list[RetrievalResult] = []
        for row in results:
            if row.chunk.kb_id in multiscale_kb_ids:
                continue
            if row.context_text is None:
                row.context_text = row.chunk.content
            fallback_results.append(row)

        return selected_results + fallback_results

    async def retrieve(
        self,
        *,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> list[RetrievalResult]:
        """检索相关 chunk。"""
        deadline = self._make_deadline(timeout_seconds)
        if not kb_ids:
            self._last_layer_draft = self._empty_layer_draft()
            return []

        if deadline is not None and float(timeout_seconds) <= 0:
            normalized_query = self._normalize_query(query)
            if top_k is None:
                top_k = self._settings.retrieval_default_top_k
            top_k = min(top_k, self._settings.retrieval_max_top_k)
            self._last_layer_draft = self._empty_layer_draft(reason="timeout")
            self._last_stats = RetrievalStats(
                query=query,
                normalized_query=normalized_query,
                effective_query=normalized_query,
                top_k=top_k,
                min_score=self._settings.retrieval_min_score,
                total_hits=0,
                filtered_count=0,
                returned_count=0,
                cache_hit=False,
                rewrite_enabled=self._settings.retrieval_query_rewrite_enabled,
                rewrite_applied=False,
                rewrite_reason="timeout",
                rewrite_latency_ms=None,
                hybrid_enabled=self._settings.retrieval_hybrid_enabled,
                hybrid_ranker=(
                    self._settings.retrieval_hybrid_ranker
                    if self._settings.retrieval_hybrid_enabled
                    else None
                ),
                rerank_enabled=self._settings.retrieval_rerank_enabled,
                reason="timeout",
            )
            return []

        normalized_query = self._normalize_query(query)

        # 应用配置限制
        if top_k is None:
            top_k = self._settings.retrieval_default_top_k
        top_k = min(top_k, self._settings.retrieval_max_top_k)

        def _timeout_return() -> list[RetrievalResult]:
            self._last_layer_draft = self._empty_layer_draft(reason="timeout")
            self._last_stats = RetrievalStats(
                query=query,
                normalized_query=normalized_query,
                effective_query=normalized_query,
                top_k=top_k,
                min_score=self._settings.retrieval_min_score,
                total_hits=0,
                filtered_count=0,
                returned_count=0,
                cache_hit=False,
                rewrite_enabled=self._settings.retrieval_query_rewrite_enabled,
                rewrite_applied=False,
                rewrite_reason="timeout",
                rewrite_latency_ms=None,
                hybrid_enabled=self._settings.retrieval_hybrid_enabled,
                hybrid_ranker=(
                    self._settings.retrieval_hybrid_ranker
                    if self._settings.retrieval_hybrid_enabled
                    else None
                ),
                rerank_enabled=self._settings.retrieval_rerank_enabled,
                reason="timeout",
            )
            return []

        try:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            kb_configs = await self._run_with_timeout(
                self._load_kb_index_configs(kb_ids), timeout_value
            )
        except asyncio.TimeoutError:
            return _timeout_return()
        kb_fingerprint = self._build_kb_fingerprint(kb_configs)

        remaining = self._remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            return _timeout_return()
        rewrite_result = await self._maybe_rewrite_query(
            normalized_query, timeout_seconds=remaining
        )
        effective_query = rewrite_result.query or normalized_query
        if not effective_query.strip():
            effective_query = normalized_query
            rewrite_result = RewriteResult(
                query=effective_query,
                rewritten=False,
                reason="empty",
                latency_ms=rewrite_result.latency_ms,
            )

        strategy = self._strategy_fingerprint(top_k, kb_fingerprint)
        cache_key = self._cache_key(effective_query, kb_ids, top_k, strategy)
        if self._redis and self._settings.retrieval_cache_enabled:
            timeout_value = self._effective_timeout(
                deadline=deadline, per_call_timeout=None
            )
            if timeout_value is not None and timeout_value <= 0:
                return _timeout_return()
            try:
                cached = await self._run_with_timeout(
                    self._redis.get(cache_key), timeout_value
                )
            except asyncio.TimeoutError:
                return _timeout_return()
            except Exception as exc:  # pragma: no cover
                logger.warning("检索缓存读取失败，跳过缓存", extra={"error": str(exc)})
                cached = None
            if cached:
                timeout_value = self._effective_timeout(
                    deadline=deadline, per_call_timeout=None
                )
                if timeout_value is not None and timeout_value <= 0:
                    return _timeout_return()
                try:
                    results = await self._run_with_timeout(
                        self._load_from_cache(cached), timeout_value
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if timeout_value is not None and timeout_value <= 0:
                        return _timeout_return()
                    await self._run_with_timeout(
                        self._hydrate_chunks_from_postgres(
                            [r.chunk for r in results]
                        ),
                        timeout_value,
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()
                try:
                    timeout_value = self._effective_timeout(
                        deadline=deadline, per_call_timeout=None
                    )
                    if timeout_value is not None and timeout_value <= 0:
                        return _timeout_return()
                    results = await self._apply_parent_child_strategy(
                        results, kb_configs, timeout_seconds=timeout_value
                    )
                except asyncio.TimeoutError:
                    return _timeout_return()
                results, filtered_count = self._apply_min_score(results)

                # Cache path has no per-query provenance. Still expose evidence draft.
                evidence_items: list[dict] = []
                for r in results:
                    evidence_items.append(
                        {
                            "source_kind": "kb",
                            "kb_id": str(r.chunk.kb_id),
                            "material_id": str(r.chunk.material_id),
                            "chunk_id": str(r.chunk.id),
                            "locator": r.chunk.locator,
                            "excerpt": (r.chunk.content or "")[:500],
                            "score": float(r.score),
                            "hits": [],
                        }
                    )
                self._last_layer_draft = RetrievalLayerDraft(
                    retrieval_candidates=[],
                    reranked_candidates=[],
                    evidence_items=evidence_items,
                    results=results,
                    stats={
                        "cache_hit": True,
                        "filtered_count": filtered_count,
                    },
                )

                self._last_stats = RetrievalStats(
                    query=query,
                    normalized_query=normalized_query,
                    effective_query=effective_query,
                    top_k=top_k,
                    min_score=self._settings.retrieval_min_score,
                    total_hits=len(results) + filtered_count,
                    filtered_count=filtered_count,
                    returned_count=len(results),
                    cache_hit=True,
                    rewrite_enabled=self._settings.retrieval_query_rewrite_enabled,
                    rewrite_applied=rewrite_result.rewritten,
                    rewrite_reason=rewrite_result.reason,
                    rewrite_latency_ms=rewrite_result.latency_ms,
                    hybrid_enabled=self._settings.retrieval_hybrid_enabled,
                    hybrid_ranker=(
                        self._settings.retrieval_hybrid_ranker
                        if self._settings.retrieval_hybrid_enabled
                        else None
                    ),
                    rerank_enabled=self._settings.retrieval_rerank_enabled,
                )
                return results

        # Unified retrieval layer: dense + BM25 + RRF (+ optional rerank) + Top-N.
        query_items = build_query_items(main_query=effective_query)
        remaining = self._remaining_seconds(deadline)
        if remaining is not None and remaining <= 0:
            return _timeout_return()
        layer = await self.retrieve_layer(
            query_items=query_items,
            kb_ids=kb_ids,
            top_n=top_k,
            per_query_top_k=top_k,
            # Keep defaults conservative: global cap and rerank cap follow Settings max_top_k.
            global_candidates_limit=self._settings.retrieval_max_top_k,
            rerank_input_limit=self._settings.retrieval_max_top_k,
            timeout_seconds=remaining,
        )
        results = layer.results
        total_hits = int(
            layer.stats.get("pre_min_score_candidates")
            or layer.stats.get("rrf_candidates")
            or 0
        )
        filtered_count = int(layer.stats.get("filtered_count") or 0)

        if not results:
            self._last_stats = RetrievalStats(
                query=query,
                normalized_query=normalized_query,
                effective_query=effective_query,
                top_k=top_k,
                min_score=self._settings.retrieval_min_score,
                total_hits=0,
                filtered_count=0,
                returned_count=0,
                cache_hit=False,
                rewrite_enabled=self._settings.retrieval_query_rewrite_enabled,
                rewrite_applied=rewrite_result.rewritten,
                rewrite_reason=rewrite_result.reason,
                rewrite_latency_ms=rewrite_result.latency_ms,
                hybrid_enabled=self._settings.retrieval_hybrid_enabled,
                hybrid_ranker=(
                    self._settings.retrieval_hybrid_ranker
                    if self._settings.retrieval_hybrid_enabled
                    else None
                ),
                rerank_enabled=self._settings.retrieval_rerank_enabled,
                reason=cast(str | None, layer.stats.get("reason")),
            )
            return []

        # 写入缓存
        if self._redis and self._settings.retrieval_cache_enabled and results:
            cache_data = [
                {"chunk_id": str(r.chunk.id), "score": r.score} for r in results
            ]
            try:
                await self._redis.set(
                    cache_key,
                    json.dumps(cache_data),
                    ex=self._settings.retrieval_cache_ttl_seconds,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("检索缓存写入失败，跳过缓存", extra={"error": str(exc)})

        self._last_stats = RetrievalStats(
            query=query,
            normalized_query=normalized_query,
            effective_query=effective_query,
            top_k=top_k,
            min_score=self._settings.retrieval_min_score,
            total_hits=total_hits,
            filtered_count=filtered_count,
            returned_count=len(results),
            cache_hit=False,
            rewrite_enabled=self._settings.retrieval_query_rewrite_enabled,
            rewrite_applied=rewrite_result.rewritten,
            rewrite_reason=rewrite_result.reason,
            rewrite_latency_ms=rewrite_result.latency_ms,
            hybrid_enabled=self._settings.retrieval_hybrid_enabled,
            hybrid_ranker=(
                self._settings.retrieval_hybrid_ranker
                if self._settings.retrieval_hybrid_enabled
                else None
            ),
            rerank_enabled=self._settings.retrieval_rerank_enabled,
            rerank_applied=bool(layer.stats.get("rerank_applied")),
            rerank_reason=cast(str | None, layer.stats.get("rerank_reason")),
            rerank_latency_ms=cast(int | None, layer.stats.get("rerank_latency_ms")),
            reason=cast(str | None, layer.stats.get("reason")),
        )

        return results

    async def _load_from_cache(self, cached: str) -> list[RetrievalResult]:
        """从缓存加载结果。"""
        data = json.loads(cached)
        chunk_ids = [str(item["chunk_id"]) for item in data]
        scores = {str(item["chunk_id"]): item["score"] for item in data}

        records = await self._milvus.query_by_chunk_ids(chunk_ids=chunk_ids)
        chunks_map: dict[str, RetrievedChunk] = {}
        for record in records:
            chunk = self._build_chunk_from_record(record)
            if chunk:
                chunks_map[str(chunk.id)] = chunk

        results: list[RetrievalResult] = []
        for item in data:
            chunk = chunks_map.get(str(item["chunk_id"]))
            if chunk:
                results.append(
                    RetrievalResult(
                        chunk=chunk,
                        score=scores[str(item["chunk_id"])],
                    )
                )
        return results

    def _apply_min_score(
        self, results: list[RetrievalResult]
    ) -> tuple[list[RetrievalResult], int]:
        min_score = self._settings.retrieval_min_score
        if min_score is None or min_score <= 0:
            return results, 0
        filtered = [r for r in results if r.score >= min_score]
        return filtered, max(len(results) - len(filtered), 0)

    def to_evidence_items(self, results: list[RetrievalResult]) -> list[EvidenceItem]:
        """将检索结果转换为证据条目。"""
        items: list[EvidenceItem] = []
        for r in results:
            items.append(
                EvidenceItem(
                    source_kind=EvidenceSourceKind.KB,
                    kb_id=r.chunk.kb_id,
                    material_id=r.chunk.material_id,
                    chunk_id=r.chunk.id,
                    locator=r.chunk.locator,
                    excerpt=r.chunk.content[:500],
                )
            )
        return items
