from __future__ import annotations

import logging
from typing import Any

from app.core.settings import Settings, get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.services.semantic_cache.models import (
    SemanticCacheHit,
    SemanticCacheLookupRequest,
    SemanticCacheScope,
    SemanticCacheStoreRequest,
)
from app.services.semantic_cache.policy import build_context
from app.services.semantic_cache.redisvl_backend import (
    RedisVLSemanticCacheBackend,
    SemanticCacheBackend,
)
from app.utils.text_sanitization import sanitize_visible_text

logger = logging.getLogger(__name__)


class KbChatSemanticCacheService:
    def __init__(
        self,
        *,
        embedding: EmbeddingClient,
        settings: Settings | None = None,
        backend: SemanticCacheBackend | None = None,
    ) -> None:
        self._embedding = embedding
        self._settings = settings or get_settings()
        self._backend = backend or RedisVLSemanticCacheBackend(self._settings)

    def enabled(self) -> bool:
        return bool(getattr(self._settings, "kb_chat_semantic_cache_enabled", True))

    def similarity_threshold(self) -> float:
        return max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        self._settings,
                        "kb_chat_semantic_cache_similarity_threshold",
                        0.88,
                    )
                ),
            ),
        )

    def ttl_seconds(self) -> int:
        return max(
            0,
            int(
                getattr(
                    self._settings, "kb_chat_semantic_cache_ttl_seconds", 24 * 60 * 60
                )
            ),
        )

    def status(self) -> dict[str, Any]:
        if not self.enabled():
            return {
                "status": "disabled",
                "backend": "redisvl",
                "enabled": False,
                "reason": None,
            }
        backend_status = self._backend.status()
        backend_status.setdefault("enabled", True)
        return backend_status

    async def lookup(
        self,
        *,
        question: str,
        scope: SemanticCacheScope,
        pre_context: dict[str, Any],
    ) -> SemanticCacheHit | None:
        if not self.enabled():
            return None
        normalized_question = sanitize_visible_text(str(question or ""))
        if not normalized_question:
            return None
        vector = await self._embed_question(
            question=normalized_question,
            stage="semantic_cache_lookup",
        )
        if vector is None:
            return None
        request = SemanticCacheLookupRequest(
            question=normalized_question,
            question_vector=vector,
            scope=scope,
            context=build_context(
                question=normalized_question, pre_context=pre_context
            ),
            similarity_threshold=self.similarity_threshold(),
            ttl_seconds=self.ttl_seconds(),
        )
        return await self._backend.lookup(request)

    async def store(
        self,
        *,
        question: str,
        answer: str,
        scope: SemanticCacheScope,
        pre_context: dict[str, Any],
        evidence: list[dict[str, Any]],
        citation_ids: list[str],
        evidence_fingerprint: list[str],
        stage_summaries: dict[str, Any],
        metrics: dict[str, Any],
        source_run_id: str | None,
    ) -> None:
        if not self.enabled():
            return
        normalized_question = sanitize_visible_text(str(question or ""))
        normalized_answer = str(answer or "").strip()
        if not normalized_question or not normalized_answer:
            return
        vector = await self._embed_question(
            question=normalized_question,
            stage="semantic_cache_write",
        )
        if vector is None:
            return
        request = SemanticCacheStoreRequest(
            question=normalized_question,
            answer=normalized_answer,
            question_vector=vector,
            scope=scope,
            context=build_context(
                question=normalized_question, pre_context=pre_context
            ),
            evidence=evidence,
            citation_ids=list(citation_ids),
            evidence_fingerprint=list(evidence_fingerprint),
            stage_summaries=dict(stage_summaries),
            metrics=dict(metrics),
            source_run_id=source_run_id,
            ttl_seconds=self.ttl_seconds(),
        )
        await self._backend.store(request)

    async def _embed_question(self, *, question: str, stage: str) -> list[float] | None:
        try:
            embeddings = await self._embedding.embed(texts=[question], stage=stage)
        except Exception as exc:
            logger.warning("语义缓存 embedding 失败: %s", exc)
            return None
        if not isinstance(embeddings, list) or not embeddings:
            return None
        return self._as_float_vector(embeddings[0])

    @staticmethod
    def _as_float_vector(value: Any) -> list[float] | None:
        if not isinstance(value, list) or not value:
            return None
        result: list[float] = []
        for item in value:
            if isinstance(item, bool):
                return None
            if not isinstance(item, (int, float)):
                return None
            result.append(float(item))
        return result if result else None
