from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from redisvl.extensions.cache.llm import SemanticCache
from redisvl.query.filter import Tag
from redisvl.utils.vectorize.base import BaseVectorizer

from app.core.settings import Settings, get_settings
from app.services.semantic_cache.models import (
    SemanticCacheHit,
    SemanticCacheLookupRequest,
    SemanticCacheStoreRequest,
)
from app.services.semantic_cache.policy import (
    SEMANTIC_CACHE_ANSWER_CONTRACT_VERSION,
    SEMANTIC_CACHE_HIT_TYPE_STRONG,
    SEMANTIC_CACHE_SCHEMA_VERSION,
    SEMANTIC_CACHE_VERIFIED_LEVEL_DIRECT,
    distance_to_similarity_score,
    similarity_threshold_to_distance,
)

logger = logging.getLogger(__name__)


class SemanticCacheBackend(Protocol):
    async def lookup(
        self, request: SemanticCacheLookupRequest
    ) -> SemanticCacheHit | None: ...

    async def store(self, request: SemanticCacheStoreRequest) -> None: ...


class _ProvidedVectorizer(BaseVectorizer):
    def __init__(self, dims: int, dtype: str = "float32") -> None:
        super().__init__(
            model="kb_chat_external_embedding", dims=int(dims), dtype=dtype
        )

    def _embed(self, content: Any = "", **kwargs) -> list[float]:
        raise RuntimeError(
            "必须显式提供 question_vector，禁止 RedisVL 内部自行生成 embedding"
        )

    def _embed_many(
        self,
        contents: list[Any] | None = None,
        texts: list[Any] | None = None,
        batch_size: int = 10,
        **kwargs,
    ) -> list[list[float]]:
        raise RuntimeError(
            "必须显式提供 question_vector，禁止 RedisVL 内部自行生成 embedding"
        )


class RedisVLSemanticCacheBackend:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._caches: dict[int, SemanticCache] = {}
        self._lock = asyncio.Lock()
        self._unavailable_reason: str | None = None

    async def lookup(
        self, request: SemanticCacheLookupRequest
    ) -> SemanticCacheHit | None:
        cache = await self._ensure_cache(len(request.question_vector))
        if cache is None:
            return None

        try:
            hits = await cache.acheck(
                prompt=request.question,
                vector=request.question_vector,
                num_results=1,
                filter_expression=self._build_filter_expression(request),
                distance_threshold=similarity_threshold_to_distance(
                    request.similarity_threshold
                ),
            )
        except Exception as exc:
            logger.warning("RedisVL semantic cache lookup 失败: %s", exc)
            return None

        if not hits:
            return None

        hit = hits[0]
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        inserted_at = hit.get("inserted_at")
        created_at = metadata.get("created_at")
        if not created_at and isinstance(inserted_at, (int, float)):
            created_at = datetime.fromtimestamp(
                inserted_at, tz=timezone.utc
            ).isoformat()
        raw_vector_distance = hit.get("vector_distance")
        try:
            vector_distance = (
                float(raw_vector_distance) if raw_vector_distance is not None else 1.0
            )
        except (TypeError, ValueError):
            vector_distance = 1.0
        score = distance_to_similarity_score(vector_distance)

        return SemanticCacheHit(
            answer=str(hit.get("response") or "").strip(),
            evidence=metadata.get("evidence")
            if isinstance(metadata.get("evidence"), list)
            else [],
            stage_summaries=(
                metadata.get("stage_summaries")
                if isinstance(metadata.get("stage_summaries"), dict)
                else {}
            ),
            metrics=metadata.get("metrics")
            if isinstance(metadata.get("metrics"), dict)
            else {},
            score=score,
            threshold=request.similarity_threshold,
            ttl_seconds=request.ttl_seconds,
            entry_id=str(hit.get("entry_id") or "").strip() or None,
            schema_version=str(metadata.get("schema_version") or "").strip()
            or SEMANTIC_CACHE_SCHEMA_VERSION,
            hit_type=str(metadata.get("hit_type") or "").strip()
            or SEMANTIC_CACHE_HIT_TYPE_STRONG,
            created_at=str(created_at or "").strip() or None,
            context_fingerprint=(
                request.context.signature
                if request.context.mode == "contextual"
                else None
            ),
            kb_version=str(metadata.get("kb_version") or "").strip()
            or request.scope.kb_version,
        )

    async def store(self, request: SemanticCacheStoreRequest) -> None:
        cache = await self._ensure_cache(len(request.question_vector))
        if cache is None:
            return

        created_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "schema_version": SEMANTIC_CACHE_SCHEMA_VERSION,
            "question": request.question,
            "question_normalized": request.question,
            "context_mode": request.context.mode,
            "context_signature": request.context.signature,
            "evidence": request.evidence,
            "citation_ids": request.citation_ids,
            "evidence_fingerprint": request.evidence_fingerprint,
            "verified_level": SEMANTIC_CACHE_VERIFIED_LEVEL_DIRECT,
            "hit_type": SEMANTIC_CACHE_HIT_TYPE_STRONG,
            "source_run_id": request.source_run_id,
            "kb_version": request.scope.kb_version,
            "answer_contract_version": SEMANTIC_CACHE_ANSWER_CONTRACT_VERSION,
            "stage_summaries": request.stage_summaries,
            "metrics": request.metrics,
            "created_at": created_at,
        }
        filters = {
            "scope_fingerprint": request.scope.scope_fingerprint,
            "mode": request.scope.mode or "unknown",
            "allow_external": "true" if request.scope.allow_external else "false",
            "kb_version": request.scope.kb_version or "kb_unknown",
            "config_fingerprint": request.scope.config_fingerprint or "config_unknown",
            "context_mode": request.context.mode,
            "context_signature": request.context.signature or "none",
            "verified_level": SEMANTIC_CACHE_VERIFIED_LEVEL_DIRECT,
            "answer_contract_version": SEMANTIC_CACHE_ANSWER_CONTRACT_VERSION,
        }

        try:
            await cache.astore(
                prompt=request.question,
                response=request.answer,
                vector=request.question_vector,
                metadata=metadata,
                filters=filters,
                ttl=request.ttl_seconds,
            )
        except Exception as exc:
            logger.warning("RedisVL semantic cache 写入失败: %s", exc)

    async def _ensure_cache(self, dims: int) -> SemanticCache | None:
        if dims in self._caches:
            return self._caches[dims]
        if self._unavailable_reason is not None:
            return None

        async with self._lock:
            if dims in self._caches:
                return self._caches[dims]
            if self._unavailable_reason is not None:
                return None
            try:
                cache = await asyncio.to_thread(self._build_cache, dims)
            except Exception as exc:
                self._unavailable_reason = str(exc)
                logger.warning("RedisVL semantic cache 初始化失败: %s", exc)
                return None
            self._caches[dims] = cache
            return cache

    def _build_cache(self, dims: int) -> SemanticCache:
        return SemanticCache(
            name=getattr(
                self._settings,
                "kb_chat_semantic_cache_index_name",
                "kb_chat_semantic_cache_v4",
            ),
            distance_threshold=similarity_threshold_to_distance(
                float(
                    getattr(
                        self._settings,
                        "kb_chat_semantic_cache_similarity_threshold",
                        0.88,
                    )
                )
            ),
            ttl=max(
                0,
                int(
                    getattr(
                        self._settings,
                        "kb_chat_semantic_cache_ttl_seconds",
                        24 * 60 * 60,
                    )
                ),
            ),
            vectorizer=_ProvidedVectorizer(dims=dims),
            filterable_fields=[
                {"name": "scope_fingerprint", "type": "tag"},
                {"name": "mode", "type": "tag"},
                {"name": "allow_external", "type": "tag"},
                {"name": "kb_version", "type": "tag"},
                {"name": "config_fingerprint", "type": "tag"},
                {"name": "context_mode", "type": "tag"},
                {"name": "context_signature", "type": "tag"},
                {"name": "verified_level", "type": "tag"},
                {"name": "answer_contract_version", "type": "tag"},
            ],
            redis_url=self._settings.redis_url,
            connection_kwargs={
                "socket_timeout": self._settings.redis_socket_timeout_seconds,
                "socket_connect_timeout": self._settings.redis_socket_connect_timeout_seconds,
                "decode_responses": True,
            },
        )

    @staticmethod
    def _build_filter_expression(request: SemanticCacheLookupRequest):
        expr = (
            (Tag("scope_fingerprint") == request.scope.scope_fingerprint)
            & (Tag("verified_level") == SEMANTIC_CACHE_VERIFIED_LEVEL_DIRECT)
            & (Tag("answer_contract_version") == SEMANTIC_CACHE_ANSWER_CONTRACT_VERSION)
            & (Tag("context_mode") == request.context.mode)
        )
        if request.context.mode == "contextual":
            signature = request.context.signature or "none"
            expr = expr & (Tag("context_signature") == signature)
        return expr
