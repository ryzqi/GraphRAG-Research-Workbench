from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.core.settings import Settings
import app.worker.task_resources as task_resources


def _settings() -> Settings:
    return Settings(_env_file=None)


@asynccontextmanager
async def _session_scope():
    yield object()


class _FakeSessionmaker:
    def __call__(self):
        return _session_scope()


class _FakeEmbeddingClient:
    def __init__(self, *, http_client, settings) -> None:
        self.http_client = http_client
        self.settings = settings


class _FakeMilvus:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class _FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


@pytest.mark.asyncio
async def test_managed_task_resources_reuses_heavy_clients_across_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await task_resources.reset_shared_task_resources()
    created_engines: list[_FakeEngine] = []
    created_sessionmakers: list[_FakeSessionmaker] = []
    created_http_clients: list[object] = []
    created_milvus: list[_FakeMilvus] = []

    async def fake_initialize(*, sessionmaker, settings) -> None:
        del sessionmaker, settings

    refresh_calls = 0

    async def fake_refresh(*, db, settings) -> None:
        nonlocal refresh_calls
        del db, settings
        refresh_calls += 1

    def fake_create_engine(settings: Settings, *, use_null_pool: bool = False) -> _FakeEngine:
        del settings, use_null_pool
        engine = _FakeEngine()
        created_engines.append(engine)
        return engine

    def fake_create_sessionmaker(*, engine) -> _FakeSessionmaker:
        assert engine is created_engines[-1]
        sessionmaker = _FakeSessionmaker()
        created_sessionmakers.append(sessionmaker)
        return sessionmaker

    def fake_create_http_client(settings: Settings, profile=None) -> object:
        del settings, profile
        client = object()
        created_http_clients.append(client)
        return client

    def fake_create_milvus_client() -> _FakeMilvus:
        client = _FakeMilvus()
        created_milvus.append(client)
        return client

    monkeypatch.setattr(task_resources, "create_engine", fake_create_engine)
    monkeypatch.setattr(task_resources, "create_sessionmaker", fake_create_sessionmaker)
    monkeypatch.setattr(task_resources, "create_http_client", fake_create_http_client)
    monkeypatch.setattr(task_resources, "create_milvus_client", fake_create_milvus_client)
    monkeypatch.setattr(task_resources, "EmbeddingClient", _FakeEmbeddingClient)
    monkeypatch.setattr(
        task_resources.ModelRuntimeConfigManager,
        "initialize",
        fake_initialize,
    )
    monkeypatch.setattr(
        task_resources.ModelRuntimeConfigManager,
        "refresh",
        fake_refresh,
    )

    async with task_resources.managed_task_resources(
        settings=_settings(),
        with_engine=True,
        with_http=True,
        with_milvus=True,
    ) as first:
        async with task_resources.managed_task_resources(
            settings=_settings(),
            with_engine=True,
            with_http=True,
            with_milvus=True,
        ) as second:
            assert first.engine is second.engine
            assert first.sessionmaker is second.sessionmaker
            assert first.http_client is second.http_client
            assert first.embedding_http_client is second.embedding_http_client
            assert first.embedding_client is second.embedding_client
            assert first.milvus is second.milvus

    assert len(created_engines) == 1
    assert len(created_sessionmakers) == 1
    assert len(created_http_clients) == 2
    assert len(created_milvus) == 1
    assert refresh_calls == 1
    await task_resources.reset_shared_task_resources()


@pytest.mark.asyncio
async def test_reset_shared_task_resources_closes_shared_resources_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await task_resources.reset_shared_task_resources()
    closed_http_clients: list[object] = []
    closed_redis_clients: list[object] = []
    engine = _FakeEngine()
    milvus = _FakeMilvus()

    async def fake_initialize(*, sessionmaker, settings) -> None:
        del sessionmaker, settings

    async def fake_refresh(*, db, settings) -> None:
        del db, settings

    def fake_create_engine(settings: Settings, *, use_null_pool: bool = False) -> _FakeEngine:
        del settings, use_null_pool
        return engine

    def fake_create_sessionmaker(*, engine) -> _FakeSessionmaker:
        del engine
        return _FakeSessionmaker()

    def fake_create_http_client(settings: Settings, profile=None) -> object:
        del settings, profile
        return object()

    def fake_create_milvus_client() -> _FakeMilvus:
        return milvus

    async def fake_close_http_client(client: object | None) -> None:
        if client is not None:
            closed_http_clients.append(client)

    async def fake_close_redis_client(client: object | None) -> None:
        if client is not None:
            closed_redis_clients.append(client)

    monkeypatch.setattr(task_resources, "create_engine", fake_create_engine)
    monkeypatch.setattr(task_resources, "create_sessionmaker", fake_create_sessionmaker)
    monkeypatch.setattr(task_resources, "create_http_client", fake_create_http_client)
    monkeypatch.setattr(task_resources, "create_milvus_client", fake_create_milvus_client)
    monkeypatch.setattr(task_resources, "EmbeddingClient", _FakeEmbeddingClient)
    monkeypatch.setattr(task_resources, "close_http_client", fake_close_http_client)
    monkeypatch.setattr(task_resources, "close_redis_client", fake_close_redis_client)
    monkeypatch.setattr(
        task_resources.ModelRuntimeConfigManager,
        "initialize",
        fake_initialize,
    )
    monkeypatch.setattr(
        task_resources.ModelRuntimeConfigManager,
        "refresh",
        fake_refresh,
    )

    async with task_resources.managed_task_resources(
        settings=_settings(),
        with_engine=True,
        with_http=True,
        with_redis=False,
        with_milvus=True,
    ):
        pass

    await task_resources.reset_shared_task_resources()

    assert len(closed_http_clients) == 2
    assert closed_redis_clients == []
    assert milvus.closed == 1
    assert engine.dispose_calls == 1
