from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.semantic_cache.models import SemanticCacheContext, SemanticCacheLookupRequest
from app.services.semantic_cache.policy import build_scope
from app.services.semantic_cache.redisvl_backend import RedisVLSemanticCacheBackend


class _FakeCache:
    async def acheck(self, **_: object) -> list[dict[str, object]]:
        return [
            {
                "entry_id": "entry-live-1",
                "response": "live-answer",
                "vector_distance": 0.0,
                "inserted_at": 1774367769.01,
                "metadata": {
                    "schema_version": "v4",
                    "hit_type": "strong_hit",
                    "kb_version": "kb-version-live-a",
                    "stage_summaries": {"answer_review": {"passed": True}},
                    "metrics": {"semantic_cache": {"mode": "unit"}},
                    "evidence": [{"citation_id": "S1"}],
                    "created_at": "2026-03-24T15:56:09.013999+00:00",
                },
            }
        ]


@pytest.mark.asyncio
async def test_lookup_preserves_zero_vector_distance_as_full_score() -> None:
    backend = RedisVLSemanticCacheBackend(
        settings=SimpleNamespace(
            redis_url="redis://127.0.0.1:6379/0",
            redis_socket_timeout_seconds=1.0,
            redis_socket_connect_timeout_seconds=1.0,
            kb_chat_semantic_cache_index_name="kb_chat_semantic_cache_test",
            kb_chat_semantic_cache_similarity_threshold=0.88,
            kb_chat_semantic_cache_ttl_seconds=120,
        )
    )

    async def _ensure_cache(_: int) -> _FakeCache:
        return _FakeCache()

    backend._ensure_cache = _ensure_cache  # type: ignore[method-assign]

    scope = build_scope(
        kb_ids=["kb-live-a"],
        allow_external=False,
        mode="single_agent",
        config_fingerprint="cfg-live-a",
        kb_version="kb-version-live-a",
    )
    request = SemanticCacheLookupRequest(
        question="CoT 和 ToT 两个框架有什么差异",
        question_vector=[1.0, 0.0, 0.0, 0.0],
        scope=scope,
        context=SemanticCacheContext(mode="standalone", signature=None),
        similarity_threshold=0.88,
        ttl_seconds=120,
    )

    hit = await backend.lookup(request)

    assert hit is not None
    assert hit.answer == "live-answer"
    assert hit.score == 1.0
    assert hit.threshold == 0.88
