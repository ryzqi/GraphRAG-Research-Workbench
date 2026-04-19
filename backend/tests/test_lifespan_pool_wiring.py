from types import SimpleNamespace

from fastapi import FastAPI
import pytest

from app.bootstrap.app_resources import AppResources, set_app_resources
from app.bootstrap import lifespan as lifespan_module
from app.core.settings import Settings
from app.services import deep_research_runtime as dr_module


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


async def test_initialize_and_shutdown_app_state_wires_pool_in_order(
    monkeypatch,
) -> None:
    calls: list[str] = []
    app = FastAPI()
    settings = _make_settings()

    def _get_sessionmaker() -> object:
        return object()

    def _get_engine() -> object:
        return object()

    async def _ensure_ingestion_schema_ready(_engine: object) -> None:
        calls.append("schema")

    async def _model_runtime_initialize(**_kwargs: object) -> None:
        calls.append("model_runtime_init")

    async def _recover_runs(**_kwargs: object) -> None:
        calls.append("recover_runs")

    async def _pool_init(_settings: Settings) -> None:
        calls.append("pool_init")

    async def _checkpoint_init() -> None:
        calls.append("checkpoint_init")

    async def _store_init() -> None:
        calls.append("store_init")

    async def _close_http_client(_client: object) -> None:
        calls.append("close_http")

    async def _ensure_buckets() -> None:
        calls.append("ensure_buckets")

    async def _close_redis_client(_redis: object) -> None:
        calls.append("close_redis")

    async def _close_object_storage() -> None:
        calls.append("close_object_storage")

    async def _model_runtime_shutdown() -> None:
        calls.append("model_runtime_shutdown")

    async def _store_shutdown() -> None:
        calls.append("store_shutdown")

    async def _checkpoint_shutdown() -> None:
        calls.append("checkpoint_shutdown")

    async def _pool_shutdown() -> None:
        calls.append("pool_shutdown")

    async def _milvus_aclose() -> None:
        calls.append("close_milvus")

    async def _engine_dispose() -> None:
        calls.append("engine_dispose")

    def _cache_clear_engine() -> None:
        calls.append("engine_cache_clear")

    def _cache_clear_sessionmaker() -> None:
        calls.append("sessionmaker_cache_clear")

    engine = SimpleNamespace(dispose=_engine_dispose)
    http_client = object()
    embedding_http_client = object()
    redis = object()
    milvus_client = SimpleNamespace(aclose=_milvus_aclose)

    def get_engine():
        return engine

    get_engine.cache_clear = _cache_clear_engine

    def get_sessionmaker():
        return _get_sessionmaker()

    get_sessionmaker.cache_clear = _cache_clear_sessionmaker

    monkeypatch.setattr(lifespan_module, "validate_startup_settings", lambda _settings: None)
    monkeypatch.setattr(lifespan_module, "get_engine", get_engine)
    monkeypatch.setattr(lifespan_module, "get_sessionmaker", get_sessionmaker)
    monkeypatch.setattr(
        lifespan_module,
        "ensure_ingestion_schema_ready",
        _ensure_ingestion_schema_ready,
    )
    monkeypatch.setattr(
        lifespan_module.ModelRuntimeConfigManager,
        "initialize",
        _model_runtime_initialize,
    )
    monkeypatch.setattr(
        lifespan_module,
        "recover_stale_interactive_agent_runs_on_startup",
        _recover_runs,
    )
    monkeypatch.setattr(
        lifespan_module.LangGraphPostgresPool,
        "initialize",
        _pool_init,
    )
    monkeypatch.setattr(
        lifespan_module.CheckpointManager,
        "initialize",
        _checkpoint_init,
    )
    monkeypatch.setattr(
        lifespan_module.StoreManager,
        "initialize",
        _store_init,
    )
    monkeypatch.setattr(lifespan_module, "create_http_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "LLMClient", lambda **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "EmbeddingClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        lifespan_module,
        "KbChatSemanticCacheService",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(lifespan_module, "RerankClient", lambda **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "create_milvus_client", lambda: milvus_client)
    monkeypatch.setattr(lifespan_module, "create_redis_client", lambda _settings: redis)
    monkeypatch.setattr(lifespan_module, "close_http_client", _close_http_client)
    monkeypatch.setattr(lifespan_module, "close_redis_client", _close_redis_client)
    monkeypatch.setattr(
        lifespan_module.ModelRuntimeConfigManager,
        "shutdown",
        _model_runtime_shutdown,
    )
    monkeypatch.setattr(lifespan_module.StoreManager, "shutdown", _store_shutdown)
    monkeypatch.setattr(
        lifespan_module.CheckpointManager,
        "shutdown",
        _checkpoint_shutdown,
    )
    monkeypatch.setattr(
        lifespan_module.LangGraphPostgresPool,
        "shutdown",
        _pool_shutdown,
    )
    monkeypatch.setattr(
        lifespan_module,
        "create_object_storage",
        lambda _settings: SimpleNamespace(
            ensure_buckets=_ensure_buckets,
            close=_close_object_storage,
        ),
    )

    await lifespan_module._initialize_app_state(app, settings)
    assert calls.index("pool_init") < calls.index("checkpoint_init") < calls.index("store_init")

    set_app_resources(
        app,
        AppResources(
            engine=engine,
            http_client=http_client,
            embedding_http_client=embedding_http_client,
            llm_client=object(),
            milvus_client=milvus_client,
            object_storage=object(),
            embedding_client=object(),
            rerank_client=object(),
            redis=redis,
            semantic_cache_service=object(),
        ),
    )
    await lifespan_module._shutdown_app_state(app)
    assert calls.index("store_shutdown") < calls.index("checkpoint_shutdown") < calls.index("pool_shutdown")


async def test_build_deep_research_runtime_runner_initializes_pool_before_checkpoint_and_store(
    monkeypatch,
) -> None:
    calls: list[str] = []

    async def _pool_init(_settings: Settings) -> None:
        calls.append("pool_init")

    async def _checkpoint_init() -> None:
        calls.append("checkpoint_init")

    async def _store_init() -> None:
        calls.append("store_init")

    monkeypatch.setattr(dr_module.LangGraphPostgresPool, "initialize", _pool_init)
    monkeypatch.setattr(dr_module.CheckpointManager, "initialize", _checkpoint_init)
    monkeypatch.setattr(dr_module.StoreManager, "initialize", _store_init)
    monkeypatch.setattr(
        dr_module.CheckpointManager,
        "get_checkpointer",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        dr_module.StoreManager,
        "get_store",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        dr_module,
        "get_prompt_loader",
        lambda: SimpleNamespace(render_with_few_shot=lambda *_args, **_kwargs: "system"),
    )
    monkeypatch.setattr(dr_module, "create_chat_model", lambda **_kwargs: object())
    monkeypatch.setattr(
        dr_module,
        "_resolve_recovery_structured_output_method",
        lambda **_kwargs: "json_schema",
    )
    async def _create_deep_research_runtime(**_kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(
        dr_module,
        "create_deep_research_runtime",
        _create_deep_research_runtime,
    )
    monkeypatch.setattr(dr_module, "_build_workspace_context_files", lambda: {})

    await dr_module.build_deep_research_runtime_runner(
        settings=_make_settings(),
        http_client=None,
        redis=None,
    )

    assert calls == ["pool_init", "checkpoint_init", "store_init"]


async def test_initialize_app_state_cleans_partial_resources_on_failure(
    monkeypatch,
) -> None:
    calls: list[str] = []
    app = FastAPI()
    settings = _make_settings()

    async def _noop_async(*_args: object, **_kwargs: object) -> None:
        return None

    engine = SimpleNamespace(dispose=_noop_async)
    http_client = object()
    embedding_http_client = object()
    milvus_client = SimpleNamespace(
        aclose=lambda: calls.append("close_milvus_async")
    )
    object_storage = SimpleNamespace(
        ensure_buckets=lambda: calls.append("ensure_buckets_async"),
        close=lambda: calls.append("close_object_storage_async"),
    )

    async def _close_http_client(client: object) -> None:
        if client is http_client:
            calls.append("close_http")
        elif client is embedding_http_client:
            calls.append("close_embedding_http")

    async def _milvus_aclose() -> None:
        calls.append("close_milvus")

    async def _object_storage_close() -> None:
        calls.append("close_object_storage")

    async def _object_storage_ensure() -> None:
        calls.append("ensure_buckets")

    async def _model_runtime_shutdown() -> None:
        calls.append("model_runtime_shutdown")

    async def _store_shutdown() -> None:
        calls.append("store_shutdown")

    async def _checkpoint_shutdown() -> None:
        calls.append("checkpoint_shutdown")

    async def _pool_shutdown() -> None:
        calls.append("pool_shutdown")

    milvus_client = SimpleNamespace(aclose=_milvus_aclose)
    object_storage = SimpleNamespace(
        ensure_buckets=_object_storage_ensure,
        close=_object_storage_close,
    )

    def get_engine():
        return engine

    get_engine.cache_clear = lambda: None

    def get_sessionmaker():
        return object()

    get_sessionmaker.cache_clear = lambda: None

    http_clients = iter([http_client, embedding_http_client])

    monkeypatch.setattr(lifespan_module, "validate_startup_settings", lambda _settings: None)
    monkeypatch.setattr(lifespan_module, "get_engine", get_engine)
    monkeypatch.setattr(lifespan_module, "get_sessionmaker", get_sessionmaker)
    monkeypatch.setattr(lifespan_module, "ensure_ingestion_schema_ready", _noop_async)
    monkeypatch.setattr(lifespan_module.ModelRuntimeConfigManager, "initialize", _noop_async)
    monkeypatch.setattr(
        lifespan_module,
        "recover_stale_interactive_agent_runs_on_startup",
        _noop_async,
    )
    monkeypatch.setattr(lifespan_module.LangGraphPostgresPool, "initialize", _noop_async)
    monkeypatch.setattr(lifespan_module.CheckpointManager, "initialize", _noop_async)
    monkeypatch.setattr(lifespan_module.StoreManager, "initialize", _noop_async)
    monkeypatch.setattr(
        lifespan_module.ModelRuntimeConfigManager,
        "shutdown",
        _model_runtime_shutdown,
    )
    monkeypatch.setattr(lifespan_module.StoreManager, "shutdown", _store_shutdown)
    monkeypatch.setattr(
        lifespan_module.CheckpointManager,
        "shutdown",
        _checkpoint_shutdown,
    )
    monkeypatch.setattr(
        lifespan_module.LangGraphPostgresPool,
        "shutdown",
        _pool_shutdown,
    )
    monkeypatch.setattr(
        lifespan_module,
        "create_http_client",
        lambda *_args, **_kwargs: next(http_clients),
    )
    monkeypatch.setattr(lifespan_module, "LLMClient", lambda **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "EmbeddingClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        lifespan_module,
        "KbChatSemanticCacheService",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(lifespan_module, "RerankClient", lambda **_kwargs: object())
    monkeypatch.setattr(lifespan_module, "create_milvus_client", lambda: milvus_client)
    monkeypatch.setattr(
        lifespan_module,
        "create_object_storage",
        lambda _settings: object_storage,
    )
    monkeypatch.setattr(
        lifespan_module,
        "create_redis_client",
        lambda _settings: (_ for _ in ()).throw(RuntimeError("redis boom")),
    )
    monkeypatch.setattr(lifespan_module, "close_http_client", _close_http_client)
    monkeypatch.setattr(lifespan_module, "close_redis_client", _noop_async)

    with pytest.raises(RuntimeError, match="redis boom"):
        await lifespan_module._initialize_app_state(app, settings)

    assert calls == [
        "ensure_buckets",
        "close_milvus",
        "close_object_storage",
        "close_embedding_http",
        "close_http",
        "store_shutdown",
        "checkpoint_shutdown",
        "pool_shutdown",
        "model_runtime_shutdown",
    ]
