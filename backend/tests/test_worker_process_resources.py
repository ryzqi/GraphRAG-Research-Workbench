from __future__ import annotations

import pytest

from app.core.settings import Settings
from app.worker import process_resources as process_resources_module
from app.worker.async_runtime import (
    initialize_worker_async_runtime,
    run_in_worker_async_runtime,
    shutdown_worker_async_runtime,
)
from app.worker import task_resources as task_resources_module
from contextlib import AbstractAsyncContextManager


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class _FakeSessionContext(AbstractAsyncContextManager):
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSessionmaker:
    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext()


class _FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


class _FakeObjectStorage:
    def __init__(self, *, ensure_error: Exception | None = None) -> None:
        self.ensure_buckets_calls = 0
        self.close_calls = 0
        self._ensure_error = ensure_error

    async def ensure_buckets(self) -> None:
        self.ensure_buckets_calls += 1
        if self._ensure_error is not None:
            raise self._ensure_error

    async def close(self) -> None:
        self.close_calls += 1


def test_managed_task_resources_reuses_process_scoped_engine_across_worker_runtime_scopes(
    monkeypatch,
) -> None:
    settings = _make_settings()
    created_engines: list[_FakeEngine] = []

    async def _noop_async(*_args: object, **_kwargs: object) -> None:
        return None

    def _create_engine(_settings: Settings, *, use_null_pool: bool = False) -> _FakeEngine:
        assert use_null_pool is False
        engine = _FakeEngine()
        created_engines.append(engine)
        return engine

    monkeypatch.setattr(task_resources_module, "create_engine", _create_engine)
    monkeypatch.setattr(
        task_resources_module,
        "create_sessionmaker",
        lambda *, engine: _FakeSessionmaker(),
    )
    monkeypatch.setattr(
        task_resources_module.ModelRuntimeConfigManager,
        "initialize",
        _noop_async,
    )
    monkeypatch.setattr(
        task_resources_module.ModelRuntimeConfigManager,
        "refresh",
        _noop_async,
    )

    async def _acquire_engine() -> _FakeEngine:
        async with task_resources_module.managed_task_resources(
            settings=settings,
            with_engine=True,
            with_http=False,
            with_redis=False,
            with_milvus=False,
            with_object_storage=False,
        ) as resources:
            assert isinstance(resources.engine, _FakeEngine)
            return resources.engine

    initialize_worker_async_runtime()
    try:
        first = run_in_worker_async_runtime(_acquire_engine())
        second = run_in_worker_async_runtime(_acquire_engine())
        assert len(created_engines) == 1
        assert first is created_engines[0]
        assert second is created_engines[0]
        assert created_engines[0].dispose_calls == 0
    finally:
        run_in_worker_async_runtime(process_resources_module.shutdown_process_resources())
        shutdown_worker_async_runtime()


def test_process_scoped_resources_retry_object_storage_initialization_after_failure(
    monkeypatch,
) -> None:
    settings = _make_settings()
    failing_storage = _FakeObjectStorage(
        ensure_error=RuntimeError("ensure buckets boom"),
    )
    healthy_storage = _FakeObjectStorage()
    storages = iter([failing_storage, healthy_storage])

    monkeypatch.setattr(
        task_resources_module,
        "create_object_storage",
        lambda _settings: next(storages),
    )

    async def _acquire_storage() -> _FakeObjectStorage:
        async with task_resources_module.managed_task_resources(
            settings=settings,
            with_engine=False,
            with_http=False,
            with_redis=False,
            with_milvus=False,
            with_object_storage=True,
        ) as resources:
            assert isinstance(resources.object_storage, _FakeObjectStorage)
            return resources.object_storage

    initialize_worker_async_runtime()
    try:
        with pytest.raises(RuntimeError, match="ensure buckets boom"):
            run_in_worker_async_runtime(_acquire_storage())

        storage = run_in_worker_async_runtime(_acquire_storage())

        assert storage is healthy_storage
        assert failing_storage.ensure_buckets_calls == 1
        assert failing_storage.close_calls == 1
        assert healthy_storage.ensure_buckets_calls == 1
    finally:
        run_in_worker_async_runtime(process_resources_module.shutdown_process_resources())
        shutdown_worker_async_runtime()
