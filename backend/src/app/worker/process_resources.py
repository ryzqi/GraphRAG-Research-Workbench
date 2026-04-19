from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.db.session import create_engine, create_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.http_client import (
    HttpClientProfile,
    close_http_client,
    create_http_client,
)
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.integrations.milvus_client import MilvusClient, create_milvus_client
from app.integrations.object_storage import ObjectStorage, create_object_storage
from app.integrations.redis_client import (
    RedisClient,
    close_redis_client,
    create_redis_client,
)
from app.worker.async_runtime import is_running_in_worker_async_runtime

MODEL_RUNTIME_REFRESH_TTL_SECONDS = 30.0


@dataclass(slots=True)
class ProcessScopedResources:
    settings: Settings
    engine: AsyncEngine | None = None
    sessionmaker: async_sessionmaker[AsyncSession] | None = None
    http_client: httpx.AsyncClient | None = None
    embedding_http_client: httpx.AsyncClient | None = None
    embedding_client: EmbeddingClient | None = None
    redis: RedisClient | None = None
    milvus: MilvusClient | None = None
    object_storage: ObjectStorage | None = None


@dataclass(slots=True)
class _ProcessResourceState:
    loop: asyncio.AbstractEventLoop
    resources: ProcessScopedResources
    init_lock: asyncio.Lock
    model_runtime_refreshed_at: float | None = None


_PROCESS_RESOURCE_STATE: _ProcessResourceState | None = None


async def _close_process_resources(
    resources: ProcessScopedResources | None,
    *,
    close_http_client_fn: Callable[[httpx.AsyncClient | None], Awaitable[None]] = close_http_client,
    close_redis_client_fn: Callable[[RedisClient | None], Awaitable[None]] = close_redis_client,
) -> None:
    if resources is None:
        return
    await close_http_client_fn(resources.http_client)
    await close_http_client_fn(resources.embedding_http_client)
    await close_redis_client_fn(resources.redis)
    if resources.object_storage is not None:
        try:
            await resources.object_storage.close()
        except Exception:  # pragma: no cover - best effort
            pass
    if resources.milvus is not None:
        try:
            await resources.milvus.aclose()
        except Exception:  # pragma: no cover - best effort
            pass
    if resources.engine is not None:
        try:
            await resources.engine.dispose()
        except Exception:  # pragma: no cover - best effort
            pass


def _require_process_resource_state(settings: Settings) -> _ProcessResourceState:
    global _PROCESS_RESOURCE_STATE

    if not is_running_in_worker_async_runtime():
        raise RuntimeError("process-scoped worker resources 只能在 worker async runtime loop 内使用")

    loop = asyncio.get_running_loop()
    state = _PROCESS_RESOURCE_STATE
    if state is None:
        state = _ProcessResourceState(
            loop=loop,
            resources=ProcessScopedResources(settings=settings),
            init_lock=asyncio.Lock(),
        )
        _PROCESS_RESOURCE_STATE = state
        return state

    if state.loop is not loop:
        raise RuntimeError("worker process resources must be shutdown before switching event loops")
    if state.resources.settings != settings:
        raise RuntimeError(
            "worker process resources does not support mixing Settings within the same worker process"
        )
    return state


async def _ensure_model_runtime_config(
    *,
    state: _ProcessResourceState,
    settings: Settings,
    force_refresh: bool,
    model_runtime_refresh: Callable[..., Awaitable[None]],
    model_runtime_refresh_ttl_seconds: float,
) -> None:
    sessionmaker = state.resources.sessionmaker
    if sessionmaker is None:
        return
    now = monotonic()
    should_refresh = force_refresh or state.model_runtime_refreshed_at is None
    if not should_refresh and state.model_runtime_refreshed_at is not None:
        should_refresh = (
            now - state.model_runtime_refreshed_at
            >= model_runtime_refresh_ttl_seconds
        )
    if not should_refresh:
        return
    async with sessionmaker() as model_config_session:
        await model_runtime_refresh(
            db=model_config_session,
            settings=settings,
        )
    state.model_runtime_refreshed_at = now


async def get_process_scoped_resources(
    *,
    settings: Settings,
    with_engine: bool,
    with_http: bool,
    with_redis: bool,
    with_milvus: bool,
    with_object_storage: bool,
    create_engine_factory: Callable[..., AsyncEngine] = create_engine,
    create_sessionmaker_factory: Callable[..., async_sessionmaker[AsyncSession]] = create_sessionmaker,
    create_http_client_factory: Callable[..., httpx.AsyncClient] = create_http_client,
    create_redis_client_factory: Callable[[Settings], RedisClient] = create_redis_client,
    create_milvus_client_factory: Callable[[], MilvusClient] = create_milvus_client,
    create_object_storage_factory: Callable[[Settings], ObjectStorage] = create_object_storage,
    model_runtime_initialize: Callable[..., Awaitable[None]] = ModelRuntimeConfigManager.initialize,
    model_runtime_refresh: Callable[..., Awaitable[None]] = ModelRuntimeConfigManager.refresh,
    model_runtime_refresh_ttl_seconds: float = MODEL_RUNTIME_REFRESH_TTL_SECONDS,
) -> ProcessScopedResources:
    state = _require_process_resource_state(settings)
    resources = state.resources

    async with state.init_lock:
        try:
            force_refresh = False
            if with_engine and resources.engine is None:
                resources.engine = create_engine_factory(settings, use_null_pool=False)
                resources.sessionmaker = create_sessionmaker_factory(engine=resources.engine)
                await model_runtime_initialize(
                    sessionmaker=resources.sessionmaker,
                    settings=settings,
                )
                force_refresh = True
            if with_http and resources.http_client is None:
                resources.http_client = create_http_client_factory(settings)
                resources.embedding_http_client = create_http_client_factory(
                    settings,
                    profile=HttpClientProfile.EMBEDDING_BATCH,
                )
                resources.embedding_client = EmbeddingClient(
                    http_client=resources.embedding_http_client,
                    settings=settings,
                )
            if with_redis and resources.redis is None:
                resources.redis = create_redis_client_factory(settings)
            if with_milvus and resources.milvus is None:
                resources.milvus = create_milvus_client_factory()
            if with_object_storage and resources.object_storage is None:
                resources.object_storage = create_object_storage_factory(settings)
                await resources.object_storage.ensure_buckets()
            if with_engine:
                await _ensure_model_runtime_config(
                    state=state,
                    settings=settings,
                    force_refresh=force_refresh,
                    model_runtime_refresh=model_runtime_refresh,
                    model_runtime_refresh_ttl_seconds=model_runtime_refresh_ttl_seconds,
                )
        except Exception:
            failed_resources = state.resources
            state.resources = ProcessScopedResources(settings=settings)
            state.model_runtime_refreshed_at = None
            try:
                await _close_process_resources(failed_resources)
            except Exception:  # pragma: no cover - rollback best effort
                pass
            raise
    return resources


async def initialize_process_resources(
    *,
    settings: Settings,
    with_engine: bool = True,
    with_http: bool = False,
    with_redis: bool = False,
    with_milvus: bool = False,
    with_object_storage: bool = False,
) -> ProcessScopedResources:
    return await get_process_scoped_resources(
        settings=settings,
        with_engine=with_engine,
        with_http=with_http,
        with_redis=with_redis,
        with_milvus=with_milvus,
        with_object_storage=with_object_storage,
    )


async def shutdown_process_resources() -> None:
    global _PROCESS_RESOURCE_STATE

    state = _PROCESS_RESOURCE_STATE
    _PROCESS_RESOURCE_STATE = None
    if state is None:
        return
    await _close_process_resources(state.resources)
