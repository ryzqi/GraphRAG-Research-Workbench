from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.semantic_cache.redisvl_backend import RedisVLSemanticCacheBackend


@pytest.mark.asyncio
async def test_semantic_cache_backend_retries_after_failure_when_cooldown_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = RedisVLSemanticCacheBackend(
        settings=SimpleNamespace(
            redis_url="redis://cache.internal:6379/0",
            redis_socket_timeout_seconds=1.0,
            redis_socket_connect_timeout_seconds=1.0,
            kb_chat_semantic_cache_index_name="kb-chat-semantic",
            kb_chat_semantic_cache_similarity_threshold=0.88,
            kb_chat_semantic_cache_ttl_seconds=300,
            kb_chat_semantic_cache_recovery_cooldown_seconds=0,
        )
    )
    cache = object()
    attempts = {"count": 0}

    def _build_cache(dims: int) -> object:
        assert dims == 1536
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("redis down")
        return cache

    monkeypatch.setattr(backend, "_build_cache", _build_cache)

    first = await backend._ensure_cache(1536)
    second = await backend._ensure_cache(1536)

    assert first is None
    assert second is cache
    assert attempts["count"] == 2
