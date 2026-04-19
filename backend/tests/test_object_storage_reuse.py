from types import SimpleNamespace

from fastapi import FastAPI

from app.bootstrap import lifespan as lifespan_module
from app.bootstrap.app_resources import require_app_resources
from app.core.settings import Settings
from app.worker import task_resources as task_resources_module


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class _FakeObjectStorage:
    def __init__(self, *, ensure_error: Exception | None = None) -> None:
        self._settings = SimpleNamespace(minio_bucket_uploads="uploads")
        self._client = SimpleNamespace(bucket_exists=lambda _bucket: True)
        self.ensure_buckets_calls = 0
        self.close_calls = 0
        self._ensure_error = ensure_error

    async def ensure_buckets(self) -> None:
        self.ensure_buckets_calls += 1
        if self._ensure_error is not None:
            raise self._ensure_error

    async def close(self) -> None:
        self.close_calls += 1


async def test_initialize_and_shutdown_app_state_wires_shared_object_storage(
    monkeypatch,
) -> None:
    app = FastAPI()
    settings = _make_settings()
    storage = _FakeObjectStorage()

    async def _noop_async(*_args: object, **_kwargs: object) -> None:
        return None

    engine = SimpleNamespace(dispose=_noop_async)

    def get_engine():
        return engine

    def _clear_engine_cache() -> None:
        return None

    get_engine.cache_clear = _clear_engine_cache

    def get_sessionmaker():
        return object()

    def _clear_sessionmaker_cache() -> None:
        return None

    get_sessionmaker.cache_clear = _clear_sessionmaker_cache

    monkeypatch.setattr(lifespan_module, "validate_startup_settings", lambda _settings: None)
    monkeypatch.setattr(lifespan_module, "get_engine", get_engine)
    monkeypatch.setattr(lifespan_module, "get_sessionmaker", get_sessionmaker)
    monkeypatch.setattr(lifespan_module, "ensure_ingestion_schema_ready", _noop_async)
    monkeypatch.setattr(
        lifespan_module.ModelRuntimeConfigManager,
        "initialize",
        _noop_async,
    )
    monkeypatch.setattr(
        lifespan_module,
        "recover_stale_interactive_agent_runs_on_startup",
        _noop_async,
    )
    monkeypatch.setattr(lifespan_module.LangGraphPostgresPool, "initialize", _noop_async)
    monkeypatch.setattr(lifespan_module.CheckpointManager, "initialize", _noop_async)
    monkeypatch.setattr(lifespan_module.StoreManager, "initialize", _noop_async)
    monkeypatch.setattr(lifespan_module, "create_http_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "LLMClient", lambda **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "EmbeddingClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        lifespan_module,
        "KbChatSemanticCacheService",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(lifespan_module, "RerankClient", lambda **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "create_milvus_client", lambda: SimpleNamespace(aclose=_noop_async))
    monkeypatch.setattr(lifespan_module, "create_redis_client", lambda _settings: object())
    monkeypatch.setattr(lifespan_module, "close_http_client", _noop_async)
    monkeypatch.setattr(lifespan_module, "close_redis_client", _noop_async)
    monkeypatch.setattr(
        lifespan_module.ModelRuntimeConfigManager,
        "shutdown",
        _noop_async,
    )
    monkeypatch.setattr(lifespan_module.StoreManager, "shutdown", _noop_async)
    monkeypatch.setattr(lifespan_module.CheckpointManager, "shutdown", _noop_async)
    monkeypatch.setattr(lifespan_module.LangGraphPostgresPool, "shutdown", _noop_async)
    monkeypatch.setattr(
        lifespan_module,
        "create_object_storage",
        lambda _settings: storage,
        raising=False,
    )

    await lifespan_module._initialize_app_state(app, settings)
    resources = require_app_resources(app)

    assert resources.object_storage is storage

    await lifespan_module._shutdown_app_state(app)

    assert storage.ensure_buckets_calls == 1
    assert storage.close_calls == 1


async def test_managed_task_resources_reuses_object_storage_within_scope(
    monkeypatch,
) -> None:
    settings = _make_settings()
    storage = _FakeObjectStorage()
    create_calls: list[Settings] = []

    def _create_object_storage(cfg: Settings) -> _FakeObjectStorage:
        create_calls.append(cfg)
        return storage

    monkeypatch.setattr(
        task_resources_module,
        "create_object_storage",
        _create_object_storage,
        raising=False,
    )

    async with task_resources_module.managed_task_resources(
        settings=settings,
        with_engine=False,
        with_object_storage=True,
    ) as outer:
        assert outer.object_storage is storage

        async with task_resources_module.managed_task_resources(
            settings=settings,
            with_engine=False,
            with_object_storage=True,
        ) as inner:
            assert inner.object_storage is storage

    assert create_calls == [settings]
    assert storage.close_calls == 1


async def test_managed_task_resources_cleans_partial_ephemeral_resources_on_failure(
    monkeypatch,
) -> None:
    settings = _make_settings()
    calls: list[str] = []
    http_client = object()
    embedding_http_client = object()
    redis = object()
    storage = _FakeObjectStorage(ensure_error=RuntimeError("ensure buckets boom"))

    async def _close_http_client(client: object | None) -> None:
        if client is http_client:
            calls.append("close_http")
        elif client is embedding_http_client:
            calls.append("close_embedding_http")

    async def _close_redis_client(client: object | None) -> None:
        if client is redis:
            calls.append("close_redis")

    async def _milvus_aclose() -> None:
        calls.append("close_milvus")

    milvus = SimpleNamespace(aclose=_milvus_aclose)
    http_clients = iter([http_client, embedding_http_client])
    monkeypatch.setattr(
        task_resources_module,
        "create_http_client",
        lambda *_args, **_kwargs: next(http_clients),
    )
    monkeypatch.setattr(task_resources_module, "create_redis_client", lambda _settings: redis)
    monkeypatch.setattr(task_resources_module, "create_milvus_client", lambda: milvus)
    monkeypatch.setattr(
        task_resources_module,
        "create_object_storage",
        lambda _settings: storage,
    )
    monkeypatch.setattr(task_resources_module, "close_http_client", _close_http_client)
    monkeypatch.setattr(task_resources_module, "close_redis_client", _close_redis_client)

    try:
        async with task_resources_module.managed_task_resources(
            settings=settings,
            with_engine=False,
            with_http=True,
            with_redis=True,
            with_milvus=True,
            with_object_storage=True,
            use_null_pool=True,
        ):
            raise AssertionError("expected managed_task_resources to fail before yielding")
    except RuntimeError as exc:
        assert str(exc) == "ensure buckets boom"
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError from ensure_buckets")

    assert storage.close_calls == 1
    assert calls == [
        "close_http",
        "close_embedding_http",
        "close_redis",
        "close_milvus",
    ]
