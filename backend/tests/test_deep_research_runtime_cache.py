import importlib
from unittest.mock import MagicMock

import pytest


def _load_cache_module():
    try:
        return importlib.import_module("app.worker.deep_research_runtime_cache")
    except ModuleNotFoundError as exc:  # pragma: no cover - red phase expectation
        pytest.fail(str(exc))


async def test_returns_cached_runner_when_key_matches(monkeypatch):
    cache_module = _load_cache_module()
    cache_module.DeepResearchRuntimeCache.reset()

    built: list[dict[str, object]] = []

    async def _fake_build(*, settings, http_client, redis):
        built.append(
            {
                "settings": settings,
                "http_client": http_client,
                "redis": redis,
            }
        )
        return MagicMock(name="Runner")

    class _Settings:
        def model_dump(self, mode="json"):
            return {"x": 1}

    class _Snapshot:
        version = 5

    monkeypatch.setattr(
        cache_module,
        "build_deep_research_runtime_runner",
        _fake_build,
    )
    monkeypatch.setattr(
        cache_module.ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(lambda cls, settings=None: _Snapshot()),
    )

    settings = _Settings()
    try:
        first = await cache_module.get_cached_runner(settings=settings)
        second = await cache_module.get_cached_runner(settings=settings)
    finally:
        cache_module.DeepResearchRuntimeCache.reset()

    assert first is second
    assert len(built) == 1


async def test_rebuilds_on_runtime_version_change(monkeypatch):
    cache_module = _load_cache_module()
    cache_module.DeepResearchRuntimeCache.reset()

    built: list[str] = []

    async def _fake_build(*, settings, http_client, redis):
        built.append(f"build_{len(built)}")
        return MagicMock(name=f"Runner_{len(built)}")

    class _Settings:
        def model_dump(self, mode="json"):
            return {"x": 1}

    versions = iter([1, 1, 2])

    def _get_snapshot(_cls, settings=None):
        snapshot = MagicMock()
        snapshot.version = next(versions)
        return snapshot

    monkeypatch.setattr(
        cache_module,
        "build_deep_research_runtime_runner",
        _fake_build,
    )
    monkeypatch.setattr(
        cache_module.ModelRuntimeConfigManager,
        "get_snapshot",
        classmethod(_get_snapshot),
    )

    settings = _Settings()
    try:
        await cache_module.get_cached_runner(settings=settings)
        await cache_module.get_cached_runner(settings=settings)
        await cache_module.get_cached_runner(settings=settings)
    finally:
        cache_module.DeepResearchRuntimeCache.reset()

    assert built == ["build_0", "build_1"]
