from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.integrations import http_client as http_client_module
from app.main import lifespan
from app.services.chunking import ChunkingEngine
from app.worker import task_resources as task_resources_module


class _FakeAsyncClient:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeEmbeddingClient:
    def __init__(self, *, http_client=None, settings=None) -> None:
        self.http_client = http_client
        self.settings = settings
        self.calls: list[dict[str, object]] = []

    async def embed(self, *, texts: list[str], stage: str | None = None, **kwargs):
        self.calls.append({"texts": list(texts), "stage": stage, **kwargs})
        return [[0.1, 0.2], [0.2, 0.3]][: len(texts)]


async def _async_noop(*args, **kwargs):
    return None


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        http_timeout_connect_seconds=5.0,
        http_timeout_read_seconds=30.0,
        http_timeout_write_seconds=30.0,
        http_timeout_pool_seconds=5.0,
        http_max_connections=100,
        http_max_keepalive_connections=20,
        http_keepalive_expiry_seconds=5.0,
        embedding_http_realtime_timeout_connect_seconds=1.5,
        embedding_http_realtime_timeout_read_seconds=9.0,
        embedding_http_realtime_timeout_write_seconds=9.5,
        embedding_http_realtime_timeout_pool_seconds=1.0,
        embedding_http_realtime_max_connections=11,
        embedding_http_realtime_max_keepalive_connections=7,
        embedding_http_realtime_keepalive_expiry_seconds=2.5,
        embedding_http_batch_timeout_connect_seconds=2.0,
        embedding_http_batch_timeout_read_seconds=45.0,
        embedding_http_batch_timeout_write_seconds=46.0,
        embedding_http_batch_timeout_pool_seconds=2.5,
        embedding_http_batch_max_connections=3,
        embedding_http_batch_max_keepalive_connections=2,
        embedding_http_batch_keepalive_expiry_seconds=8.0,
        app_name="test-app",
        app_cors_allow_origins=["http://localhost:3000"],
    )


def _index_config() -> SimpleNamespace:
    return SimpleNamespace(
        chunking=SimpleNamespace(
            semantic=SimpleNamespace(
                threshold_mode=SimpleNamespace(value="fixed"),
                embedding_batch_size=2,
                min_tokens=1,
                max_tokens=10,
                overlap_chars=0,
                breakpoint_percentile=90,
                similarity_threshold=0.85,
            )
        )
    )


def _with_cache_clear(fn):
    fn.cache_clear = lambda: None
    return fn


@pytest.mark.asyncio
async def test_create_http_client_applies_profile_specific_timeout_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, object]] = []

    class _CaptureAsyncClient:
        def __init__(self, *, timeout, limits) -> None:
            created.append({"timeout": timeout, "limits": limits})

    monkeypatch.setattr(http_client_module.httpx, "AsyncClient", _CaptureAsyncClient)
    settings = _settings()

    http_client_module.create_http_client(settings)
    http_client_module.create_http_client(settings, profile="embedding_realtime")
    http_client_module.create_http_client(settings, profile="embedding_batch")

    assert created[0]["timeout"].connect == 5.0
    assert created[0]["limits"].max_connections == 100
    assert created[1]["timeout"].connect == 1.5
    assert created[1]["limits"].max_connections == 11
    assert created[2]["timeout"].read == 45.0
    assert created[2]["limits"].max_connections == 3


@pytest.mark.asyncio
async def test_managed_task_resources_provides_batch_embedding_client_and_closes_both_http_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_profiles: list[str] = []
    settings = _settings()

    monkeypatch.setattr(
        task_resources_module,
        "create_http_client",
        lambda cfg, profile="default": _FakeAsyncClient(str(profile)),
    )

    async def _close_http_client(client) -> None:
        if client is not None:
            closed_profiles.append(client.profile)

    monkeypatch.setattr(task_resources_module, "close_http_client", _close_http_client)
    monkeypatch.setattr(task_resources_module, "EmbeddingClient", _FakeEmbeddingClient)

    async with task_resources_module.managed_task_resources(
        settings=settings,
        with_engine=False,
        with_http=True,
        with_redis=False,
        with_milvus=False,
    ) as resources:
        assert resources.http_client.profile == "default"
        assert resources.embedding_http_client.profile == "embedding_batch"
        assert resources.embedding_client.http_client is resources.embedding_http_client
        assert resources.embedding_client.settings is settings

    assert closed_profiles == ["default", "embedding_batch"]


@pytest.mark.asyncio
async def test_lifespan_wires_realtime_embedding_client_separately_from_default_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    settings = _settings()
    closed_profiles: list[str] = []

    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(main_module, "validate_startup_settings", lambda _settings: None)
    monkeypatch.setattr(main_module, "ensure_ingestion_schema_ready", _async_noop)
    monkeypatch.setattr(
        main_module.ModelRuntimeConfigManager,
        "initialize",
        _async_noop,
    )
    monkeypatch.setattr(
        main_module,
        "recover_stale_interactive_agent_runs_on_startup",
        _async_noop,
    )
    monkeypatch.setattr(main_module.CheckpointManager, "initialize", _async_noop)
    monkeypatch.setattr(main_module.CheckpointManager, "shutdown", _async_noop)
    monkeypatch.setattr(main_module.StoreManager, "initialize", _async_noop)
    monkeypatch.setattr(main_module.StoreManager, "shutdown", _async_noop)
    monkeypatch.setattr(main_module.DeepAgentsStoreManager, "initialize", lambda: None)
    monkeypatch.setattr(main_module.DeepAgentsStoreManager, "shutdown", lambda: None)
    monkeypatch.setattr(main_module.ModelRuntimeConfigManager, "shutdown", _async_noop)

    class _FakeEngine:
        async def dispose(self) -> None:
            return None

    class _FakeMilvus:
        async def aclose(self) -> None:
            return None

    fake_engine = _FakeEngine()
    monkeypatch.setattr(main_module, "get_engine", _with_cache_clear(lambda: fake_engine))
    monkeypatch.setattr(
        main_module,
        "get_sessionmaker",
        _with_cache_clear(lambda: SimpleNamespace()),
    )
    monkeypatch.setattr(
        main_module,
        "create_http_client",
        lambda cfg, profile="default": _FakeAsyncClient(str(profile)),
    )

    async def _close_http_client(client) -> None:
        if client is not None:
            closed_profiles.append(client.profile)

    monkeypatch.setattr(main_module, "close_http_client", _close_http_client)
    monkeypatch.setattr(main_module, "LLMClient", lambda http_client: SimpleNamespace(http_client=http_client))
    monkeypatch.setattr(main_module, "EmbeddingClient", _FakeEmbeddingClient)
    monkeypatch.setattr(
        main_module,
        "RerankClient",
        lambda settings, http_client: SimpleNamespace(settings=settings, http_client=http_client),
    )
    monkeypatch.setattr(main_module, "create_milvus_client", lambda: _FakeMilvus())
    monkeypatch.setattr(main_module, "create_redis_client", lambda _settings: SimpleNamespace())
    monkeypatch.setattr(main_module, "close_redis_client", _async_noop)

    app = SimpleNamespace(state=SimpleNamespace())

    @asynccontextmanager
    async def _run_lifespan():
        async with lifespan(app):
            yield

    async with _run_lifespan():
        assert app.state.http_client.profile == "default"
        assert app.state.embedding_http_client.profile == "embedding_realtime"
        assert app.state.embedding_client.http_client is app.state.embedding_http_client
        assert app.state.embedding_client.settings is settings

    assert closed_profiles == ["default", "embedding_realtime"]


@pytest.mark.asyncio
async def test_chunking_engine_uses_chunking_stage_for_semantic_embedding_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding = _FakeEmbeddingClient()
    monkeypatch.setattr("app.services.chunking._split_sentences", lambda text: ["Alpha.", "Beta."])
    monkeypatch.setattr("app.services.chunking.count_tokens", lambda text, model=None: 1)
    monkeypatch.setattr("app.services.chunking._resolve_semantic_threshold", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.services.chunking._enforce_semantic_max_tokens",
        lambda chunks, **kwargs: chunks,
    )

    engine = ChunkingEngine(settings=SimpleNamespace(embedding_model="test-model"), embedding=embedding)

    result = await engine._split_semantic("Alpha. Beta.", _index_config())

    assert len(result.chunks) == 1
    assert "Alpha." in result.chunks[0]
    assert "Beta." in result.chunks[0]
    assert embedding.calls == [
        {
            "texts": ["Alpha.", "Beta."],
            "stage": "chunking",
        }
    ]
