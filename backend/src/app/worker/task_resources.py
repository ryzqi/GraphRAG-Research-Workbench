from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import AsyncIterator, Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.settings import Settings, get_settings
from app.db.session import create_engine, create_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.http_client import (
    HttpClientProfile,
    close_http_client,
    create_http_client,
)
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.integrations.milvus_client import MilvusClient, create_milvus_client
from app.integrations.redis_client import (
    RedisClient,
    close_redis_client,
    create_redis_client,
)
from app.services.parsing.url_parser import UrlCrawler, close_url_crawler, create_url_crawler

logger = logging.getLogger(__name__)
MODEL_RUNTIME_REFRESH_TTL_SECONDS = 30.0


@dataclass(slots=True)
class TaskResources:
    settings: Settings
    engine: AsyncEngine | None = None
    sessionmaker: async_sessionmaker[AsyncSession] | None = None
    http_client: httpx.AsyncClient | None = None
    embedding_http_client: httpx.AsyncClient | None = None
    embedding_client: EmbeddingClient | None = None
    redis: RedisClient | None = None
    milvus: MilvusClient | None = None
    url_crawler: UrlCrawler | None = None
    _url_crawler_factory: Callable[..., Awaitable[UrlCrawler]] | None = None
    _url_crawler_lock: asyncio.Lock | None = None
    _url_crawler_unavailable: bool = False

    async def get_url_crawler(self) -> UrlCrawler | None:
        if self.url_crawler is not None:
            return self.url_crawler
        if self._url_crawler_unavailable or self._url_crawler_factory is None:
            return None
        if self._url_crawler_lock is None:
            self._url_crawler_lock = asyncio.Lock()

        async with self._url_crawler_lock:
            if self.url_crawler is not None:
                return self.url_crawler
            if self._url_crawler_unavailable:
                return None
            try:
                self.url_crawler = await self._url_crawler_factory(
                    settings=self.settings
                )
            except Exception as exc:
                self._url_crawler_unavailable = True
                logger.warning(
                    "Failed to initialize shared URL crawler resource",
                    extra={"error": str(exc)},
                )
                return None
        return self.url_crawler


@dataclass(slots=True)
class _TaskResourceScope:
    resources: TaskResources
    init_lock: asyncio.Lock
    nesting: int = 0
    model_runtime_refreshed_at: float | None = None


_TASK_RESOURCE_SCOPE: ContextVar[_TaskResourceScope | None] = ContextVar(
    "worker_task_resource_scope",
    default=None,
)


async def _close_task_resources(
    resources: TaskResources | None,
) -> None:
    if resources is None:
        return
    await close_url_crawler(resources.url_crawler)
    await close_http_client(resources.http_client)
    await close_http_client(resources.embedding_http_client)
    await close_redis_client(resources.redis)
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


async def reset_shared_task_resources() -> None:
    scope = _TASK_RESOURCE_SCOPE.get()
    if scope is None:
        return
    _TASK_RESOURCE_SCOPE.set(None)
    scope.nesting = 0
    await _close_task_resources(scope.resources)


async def _ensure_model_runtime_config(
    *,
    scope: _TaskResourceScope,
    settings: Settings,
    force_refresh: bool,
) -> None:
    sessionmaker = scope.resources.sessionmaker
    if sessionmaker is None:
        return
    now = monotonic()
    should_refresh = force_refresh or scope.model_runtime_refreshed_at is None
    if not should_refresh and scope.model_runtime_refreshed_at is not None:
        should_refresh = (
            now - scope.model_runtime_refreshed_at
            >= MODEL_RUNTIME_REFRESH_TTL_SECONDS
        )
    if not should_refresh:
        return
    async with sessionmaker() as model_config_session:
        await ModelRuntimeConfigManager.refresh(
            db=model_config_session,
            settings=settings,
        )
    scope.model_runtime_refreshed_at = now


async def _ensure_task_resource_scope(
    *,
    scope: _TaskResourceScope,
    settings: Settings,
    with_engine: bool,
    with_http: bool,
    with_redis: bool,
    with_milvus: bool,
) -> TaskResources:
    resources = scope.resources
    if resources.settings != settings:
        raise RuntimeError(
            "managed_task_resources does not support mixing Settings within the same asyncio task scope"
        )

    async with scope.init_lock:
        force_refresh = False
        if with_engine and resources.engine is None:
            resources.engine = create_engine(settings, use_null_pool=False)
            resources.sessionmaker = create_sessionmaker(engine=resources.engine)
            await ModelRuntimeConfigManager.initialize(
                sessionmaker=resources.sessionmaker,
                settings=settings,
            )
            force_refresh = True
        if with_http and resources.http_client is None:
            resources.http_client = create_http_client(settings)
            resources.embedding_http_client = create_http_client(
                settings,
                profile=HttpClientProfile.EMBEDDING_BATCH,
            )
            resources.embedding_client = EmbeddingClient(
                http_client=resources.embedding_http_client,
                settings=settings,
            )
        if with_redis and resources.redis is None:
            resources.redis = create_redis_client(settings)
        if with_milvus and resources.milvus is None:
            resources.milvus = create_milvus_client()
        if with_engine:
            await _ensure_model_runtime_config(
                scope=scope,
                settings=settings,
                force_refresh=force_refresh,
            )
    return resources


@asynccontextmanager
async def _managed_ephemeral_task_resources(
    *,
    settings: Settings,
    with_engine: bool,
    with_http: bool,
    with_redis: bool,
    with_milvus: bool,
    use_null_pool: bool,
) -> AsyncIterator[TaskResources]:
    engine = None
    sessionmaker = None
    http_client = None
    embedding_http_client = None
    embedding_client = None
    redis = None
    milvus = None

    if with_engine:
        engine = create_engine(settings, use_null_pool=use_null_pool)
        sessionmaker = create_sessionmaker(engine=engine)
        await ModelRuntimeConfigManager.initialize(
            sessionmaker=sessionmaker,
            settings=settings,
        )
        async with sessionmaker() as model_config_session:
            await ModelRuntimeConfigManager.refresh(
                db=model_config_session,
                settings=settings,
            )
    if with_http:
        http_client = create_http_client(settings)
        embedding_http_client = create_http_client(
            settings,
            profile=HttpClientProfile.EMBEDDING_BATCH,
        )
        embedding_client = EmbeddingClient(
            http_client=embedding_http_client,
            settings=settings,
        )
    if with_redis:
        redis = create_redis_client(settings)
    if with_milvus:
        milvus = create_milvus_client()

    resources = TaskResources(
        settings=settings,
        engine=engine,
        sessionmaker=sessionmaker,
        http_client=http_client,
        embedding_http_client=embedding_http_client,
        embedding_client=embedding_client,
        redis=redis,
        milvus=milvus,
        _url_crawler_factory=create_url_crawler,
    )
    try:
        yield resources
    finally:
        await _close_task_resources(resources)


@asynccontextmanager
async def managed_task_resources(
    *,
    settings: Settings | None = None,
    with_engine: bool = True,
    with_http: bool = False,
    with_redis: bool = False,
    with_milvus: bool = False,
    use_null_pool: bool = False,
) -> AsyncIterator[TaskResources]:
    """统一管理 Celery 任务资源：按单次 asyncio 调用栈复用，退出最外层时释放。"""
    cfg = settings or get_settings()
    if use_null_pool:
        async with _managed_ephemeral_task_resources(
            settings=cfg,
            with_engine=with_engine,
            with_http=with_http,
            with_redis=with_redis,
            with_milvus=with_milvus,
            use_null_pool=True,
        ) as resources:
            yield resources
        return

    scope = _TASK_RESOURCE_SCOPE.get()
    token = None
    if scope is None:
        scope = _TaskResourceScope(
            resources=TaskResources(
                settings=cfg,
                _url_crawler_factory=create_url_crawler,
            ),
            init_lock=asyncio.Lock(),
        )
        token = _TASK_RESOURCE_SCOPE.set(scope)
    scope.nesting += 1
    try:
        resources = await _ensure_task_resource_scope(
            scope=scope,
            settings=cfg,
            with_engine=with_engine,
            with_http=with_http,
            with_redis=with_redis,
            with_milvus=with_milvus,
        )
        yield resources
    finally:
        scope.nesting -= 1
        if scope.nesting == 0:
            if token is not None:
                _TASK_RESOURCE_SCOPE.reset(token)
            else:
                _TASK_RESOURCE_SCOPE.set(None)
            await _close_task_resources(scope.resources)
