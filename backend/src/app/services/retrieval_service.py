"""检索服务：Milvus 召回（Milvus-only）+ 可配置缓存。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.rerank_client import RerankClient
from app.integrations.redis_client import RedisClient
from app.models.knowledge_base import KnowledgeBase
from app.schemas.chats import EvidenceItem, EvidenceSourceKind
from app.schemas.knowledge_bases import IndexConfig
from app.services.query_rewrite_service import QueryRewriteService, RewriteResult

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

    @property
    def last_stats(self) -> RetrievalStats | None:
        return self._last_stats

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

    async def _get_query_embedding(self, query: str) -> list[float]:
        """获取查询向量（带缓存）。"""
        if self._redis and self._settings.retrieval_cache_enabled:
            cache_key = self._embedding_cache_key(query)
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning("Embedding 缓存读取失败，跳过缓存", extra={"error": str(exc)})
                cached = None
            if cached:
                logger.debug("Embedding 缓存命中", extra={"query": query[:50]})
                return json.loads(cached)

        start_time = time.perf_counter()
        embeddings = await self._embedding.embed(texts=[query])
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
                logger.warning("Embedding 缓存写入失败，跳过缓存", extra={"error": str(exc)})

        return embeddings[0]

    async def _maybe_rewrite_query(self, query: str) -> RewriteResult:
        """可选查询重写，失败回退原 query。"""
        if not self._settings.retrieval_query_rewrite_enabled:
            return RewriteResult(
                query=query,
                rewritten=False,
                reason="disabled",
                latency_ms=0,
            )

        cache_key = self._rewrite_cache_key(query)
        if self._redis and self._settings.retrieval_cache_enabled:
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning("Rewrite 缓存读取失败，跳过缓存", extra={"error": str(exc)})
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
        result = await rewriter.rewrite(query)

        if self._redis and self._settings.retrieval_cache_enabled and result.query:
            try:
                await self._redis.set(
                    cache_key,
                    result.query,
                    ex=self._settings.retrieval_cache_ttl_seconds,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Rewrite 缓存写入失败，跳过缓存", extra={"error": str(exc)})

        return result

    async def _maybe_rerank(
        self, query: str, results: list[RetrievalResult], top_k: int
    ) -> tuple[list[RetrievalResult], bool, str | None, int | None]:
        """可选 rerank，失败回退原排序。"""
        if not self._settings.retrieval_rerank_enabled:
            return results, False, "disabled", None

        if not results:
            return results, False, "empty_candidates", None

        reranker = self._reranker or RerankClient(self._settings)
        self._reranker = reranker

        start_time = time.perf_counter()
        try:
            rerank_results = await reranker.rerank(
                query=query,
                documents=[r.chunk.content for r in results],
                top_n=min(top_k, len(results)),
                timeout_seconds=self._settings.retrieval_rerank_timeout_seconds,
            )
        except Exception as exc:
            logger.warning("Rerank 调用失败，回退原排序", extra={"error": str(exc)})
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
        stmt = select(KnowledgeBase.id, KnowledgeBase.index_config).where(
            KnowledgeBase.id.in_(kb_ids)
        )
        result = await self._db.execute(stmt)
        configs: dict[uuid.UUID, IndexConfig] = {}
        for kb_id, raw in result.all():
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
            fingerprint[str(kb_id)] = {
                "parent_child": cfg.retrieval.parent_child.model_dump(mode="json"),
            }
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
    ) -> list[RetrievalResult]:
        if not results or not kb_configs:
            for r in results:
                r.context_text = r.chunk.content
            return results

        parent_ids: set[str] = set()
        selected_child_ids: set[uuid.UUID] = set()
        parent_child_kb_ids: set[uuid.UUID] = set()

        for kb_id, cfg in kb_configs.items():
            kb_results = [r for r in results if r.chunk.kb_id == kb_id]
            if not kb_results:
                continue

            if not cfg.retrieval.parent_child.enabled:
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
                parent_scores[parent_id] = max(parent_scores.get(parent_id, -1e9), r.score)

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
            parent_records = await self._milvus.query_by_chunk_ids(
                chunk_ids=list(parent_ids)
            )
            for record in parent_records:
                chunk = self._build_chunk_from_record(record)
                if chunk:
                    parent_map[str(chunk.id)] = chunk

        for r in results:
            if r.chunk.id in selected_child_ids:
                parent = parent_map.get(r.chunk.parent_chunk_id or "")
                r.context_text = (parent.content if parent else r.chunk.content)
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

    async def retrieve(
        self,
        *,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """检索相关 chunk。"""
        if not kb_ids:
            return []

        normalized_query = self._normalize_query(query)

        # 应用配置限制
        if top_k is None:
            top_k = self._settings.retrieval_default_top_k
        top_k = min(top_k, self._settings.retrieval_max_top_k)

        kb_configs = await self._load_kb_index_configs(kb_ids)
        kb_fingerprint = self._build_kb_fingerprint(kb_configs)

        rewrite_result = await self._maybe_rewrite_query(normalized_query)
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
            try:
                cached = await self._redis.get(cache_key)
            except Exception as exc:  # pragma: no cover
                logger.warning("检索缓存读取失败，跳过缓存", extra={"error": str(exc)})
                cached = None
            if cached:
                results = await self._load_from_cache(cached)
                results = await self._apply_parent_child_strategy(results, kb_configs)
                results, filtered_count = self._apply_min_score(results)
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

        # 获取查询向量（带缓存）
        query_embedding = await self._get_query_embedding(effective_query)

        # Milvus 召回
        kb_id_strs = [str(kid) for kid in kb_ids]
        hits = []
        if self._settings.retrieval_hybrid_enabled:
            try:
                hits = await self._milvus.hybrid_search(
                    embedding=query_embedding,
                    query=effective_query,
                    kb_ids=kb_id_strs,
                    top_k=top_k,
                    ranker=self._settings.retrieval_hybrid_ranker,
                    dense_weight=self._settings.retrieval_hybrid_dense_weight,
                    sparse_weight=self._settings.retrieval_hybrid_sparse_weight,
                    rrf_k=self._settings.retrieval_hybrid_rrf_k,
                )
            except Exception as exc:
                logger.warning("Hybrid 检索失败，回退 dense", extra={"error": str(exc)})
                hits = await self._milvus.search(
                    embedding=query_embedding,
                    kb_ids=kb_id_strs,
                    top_k=top_k,
                )
        else:
            hits = await self._milvus.search(
                embedding=query_embedding,
                kb_ids=kb_id_strs,
                top_k=top_k,
            )

        if not hits:
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
            )
            return []

        # 组装结果（保持召回顺序）
        results: list[RetrievalResult] = []
        for hit in hits:
            chunk = self._build_chunk_from_hit(hit)
            if chunk:
                results.append(RetrievalResult(chunk=chunk, score=hit.score))

        total_hits = len(results)
        results = await self._apply_parent_child_strategy(results, kb_configs)
        results, filtered_count = self._apply_min_score(results)

        rerank_applied = False
        rerank_reason = "disabled"
        rerank_latency_ms = None
        if results:
            results, rerank_applied, rerank_reason, rerank_latency_ms = (
                await self._maybe_rerank(effective_query, results, top_k)
            )

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
            rerank_applied=rerank_applied,
            rerank_reason=rerank_reason,
            rerank_latency_ms=rerank_latency_ms,
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
