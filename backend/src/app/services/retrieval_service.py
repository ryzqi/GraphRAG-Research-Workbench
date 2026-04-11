"""检索服务：基于 Milvus 搜索，并支持可选的缓存 / 改写 / rerank。"""

from __future__ import annotations

import asyncio
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.redis_client import RedisClient
from app.integrations.rerank_client import RerankClient
from app.services.query_rewrite_service import QueryRewriteService
from app.services.retrieval_service_context import RetrievalContextMixin
from app.services.retrieval_service_contracts import (
    RetrievalFeatureFlags,
    RetrievalLayerDraft,
    RetrievalResult,
    RetrievalRuntimeOverrides,
    RetrievalStats,
    RetrievedChunk,
)
from app.services.retrieval_service_layer_ops import RetrievalLayerOpsMixin
from app.services.retrieval_service_retrieve_ops import RetrievalRetrieveMixin
from app.services.retrieval_service_runtime import RetrievalRuntimeMixin
from app.services.retrieval_service_strategy_ops import RetrievalStrategyMixin

__all__ = [
    "RetrievedChunk",
    "RetrievalFeatureFlags",
    "RetrievalLayerDraft",
    "RetrievalResult",
    "RetrievalRuntimeOverrides",
    "RetrievalService",
    "RetrievalStats",
]


class RetrievalService(
    RetrievalRetrieveMixin,
    RetrievalLayerOpsMixin,
    RetrievalStrategyMixin,
    RetrievalRuntimeMixin,
    RetrievalContextMixin,
):
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
        self._db_lock = asyncio.Lock()

    @property
    def last_stats(self) -> RetrievalStats | None:
        return self._last_stats

    @property
    def last_layer_draft(self) -> RetrievalLayerDraft | None:
        """最近一次检索调用生成的统一检索层草稿。"""
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
    def _int_from_object(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

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

    async def _db_execute(self, stmt):
        if self._db is None:
            raise RuntimeError("db_not_configured")
        async with self._db_lock:
            return await self._db.execute(stmt)

    @staticmethod
    def _empty_layer_draft(reason: str | None = None) -> RetrievalLayerDraft:
        stats: dict[str, object] = {
            "hybrid_hits": 0,
            "rrf_candidates": 0,
            "rerank_applied": False,
            "optional_embedding_skips": [],
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