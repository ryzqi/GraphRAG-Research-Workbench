"""检索服务：Milvus 召回 + Postgres 拉取 + 可配置缓存。"""

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
from app.integrations.redis_client import RedisClient
from app.models.document_chunk import DocumentChunk
from app.schemas.chats import EvidenceItem, EvidenceSourceKind

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetrievalResult:
    chunk: DocumentChunk
    score: float


class RetrievalService:
    def __init__(
        self,
        db: AsyncSession,
        milvus: MilvusClient,
        embedding: EmbeddingClient,
        redis: RedisClient | None = None,
    ) -> None:
        self._db = db
        self._milvus = milvus
        self._embedding = embedding
        self._redis = redis
        self._settings = get_settings()

    def _cache_key(self, query: str, kb_ids: list[uuid.UUID], top_k: int) -> str:
        """生成缓存键。"""
        kb_str = ",".join(sorted(str(k) for k in kb_ids))
        raw = f"retrieval:{query}:{kb_str}:{top_k}"
        return f"retrieval:{hashlib.md5(raw.encode()).hexdigest()}"

    def _embedding_cache_key(self, query: str) -> str:
        """生成 embedding 缓存键。"""
        return f"embedding:{hashlib.md5(query.encode()).hexdigest()}"

    async def _get_query_embedding(self, query: str) -> list[float]:
        """获取查询向量（带缓存）。"""
        if self._redis and self._settings.retrieval_cache_enabled:
            cache_key = self._embedding_cache_key(query)
            cached = await self._redis.get(cache_key)
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
            await self._redis.set(
                self._embedding_cache_key(query),
                json.dumps(embeddings[0]),
                ex=self._settings.retrieval_cache_ttl_seconds * 2,
            )

        return embeddings[0]

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

        # 应用配置限制
        if top_k is None:
            top_k = self._settings.retrieval_default_top_k
        top_k = min(top_k, self._settings.retrieval_max_top_k)

        # 尝试从缓存获取
        cache_key = self._cache_key(query, kb_ids, top_k)
        if self._redis and self._settings.retrieval_cache_enabled:
            cached = await self._redis.get(cache_key)
            if cached:
                return await self._load_from_cache(cached)

        # 获取查询向量（带缓存）
        query_embedding = await self._get_query_embedding(query)

        # Milvus 召回
        kb_id_strs = [str(kid) for kid in kb_ids]
        hits = await self._milvus.search(
            embedding=query_embedding,
            kb_ids=kb_id_strs,
            top_k=top_k,
        )

        if not hits:
            return []

        # 从 Postgres 拉取 chunk 详情
        chunk_ids = [uuid.UUID(h.chunk_id) for h in hits]
        stmt = select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
        result = await self._db.execute(stmt)
        chunks_map = {c.id: c for c in result.scalars().all()}

        # 组装结果（保持召回顺序）
        results: list[RetrievalResult] = []
        for hit in hits:
            chunk = chunks_map.get(uuid.UUID(hit.chunk_id))
            if chunk:
                results.append(RetrievalResult(chunk=chunk, score=hit.score))

        # 写入缓存
        if self._redis and self._settings.retrieval_cache_enabled and results:
            cache_data = [
                {"chunk_id": str(r.chunk.id), "score": r.score} for r in results
            ]
            await self._redis.set(
                cache_key,
                json.dumps(cache_data),
                ex=self._settings.retrieval_cache_ttl_seconds,
            )

        return results

    async def _load_from_cache(self, cached: str) -> list[RetrievalResult]:
        """从缓存加载结果。"""
        data = json.loads(cached)
        chunk_ids = [uuid.UUID(item["chunk_id"]) for item in data]
        scores = {item["chunk_id"]: item["score"] for item in data}

        stmt = select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
        result = await self._db.execute(stmt)
        chunks_map = {str(c.id): c for c in result.scalars().all()}

        results: list[RetrievalResult] = []
        for item in data:
            chunk = chunks_map.get(item["chunk_id"])
            if chunk:
                results.append(RetrievalResult(chunk=chunk, score=scores[item["chunk_id"]]))
        return results

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
                    excerpt=r.chunk.text[:500],
                )
            )
        return items
