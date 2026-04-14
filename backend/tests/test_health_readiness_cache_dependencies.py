from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import health as health_endpoint


class _FakeStoreManager:
    @classmethod
    def status(cls) -> dict[str, object]:
        return {
            "status": "degraded",
            "configured_backend": "postgres",
            "effective_backend": "memory",
            "degraded": True,
            "reason": "persistent_store_unavailable",
        }


class _FakeCheckpointManager:
    @classmethod
    def status(cls) -> dict[str, object]:
        return {
            "status": "ready",
            "initialized": True,
            "backend": "postgres",
        }


class _FakeSemanticCacheService:
    def status(self) -> dict[str, object]:
        return {
            "status": "degraded",
            "enabled": True,
            "backend": "redisvl",
            "reason": "redis_connect_error",
        }


@pytest.mark.asyncio
async def test_ready_reports_cache_dependency_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok(*args, **kwargs) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(health_endpoint, "_check_postgres", _ok)
    monkeypatch.setattr(health_endpoint, "_check_redis", _ok)
    monkeypatch.setattr(health_endpoint, "_check_milvus", _ok)
    monkeypatch.setattr(health_endpoint, "_check_minio", _ok)
    monkeypatch.setattr(
        health_endpoint,
        "StoreManager",
        _FakeStoreManager,
        raising=False,
    )
    monkeypatch.setattr(
        health_endpoint,
        "CheckpointManager",
        _FakeCheckpointManager,
        raising=False,
    )

    response = await health_endpoint.ready(
        SimpleNamespace(
            engine=object(),
            redis=SimpleNamespace(ping=lambda: True),
            milvus_client=SimpleNamespace(ready_check=_ok),
            semantic_cache_service=_FakeSemanticCacheService(),
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert payload["dependencies"]["checkpointer"]["status"] == "ready"
    assert payload["dependencies"]["memory_store"]["status"] == "degraded"
    assert payload["dependencies"]["memory_store"]["degraded"] is True
    assert payload["dependencies"]["semantic_cache"]["status"] == "degraded"
