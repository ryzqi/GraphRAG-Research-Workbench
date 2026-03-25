from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

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
from app.integrations.redis_client import RedisClient, close_redis_client, create_redis_client


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
    """统一管理 Celery 任务资源：创建 + finally 释放（尽力而为）。"""
    cfg = settings or get_settings()
    engine = None
    sessionmaker = None
    http_client = None
    embedding_http_client = None
    embedding_client = None
    redis = None
    milvus = None

    if with_engine:
        engine = create_engine(cfg, use_null_pool=use_null_pool)
        sessionmaker = create_sessionmaker(engine=engine)
        await ModelRuntimeConfigManager.initialize(
            sessionmaker=sessionmaker,
            settings=cfg,
        )
        # Worker 进程生命周期较长；每次任务都刷新一次，
        # 让管理页的运行时模型配置变更无需重启即可生效。
        async with sessionmaker() as model_config_session:
            await ModelRuntimeConfigManager.refresh(
                db=model_config_session,
                settings=cfg,
            )
    if with_http:
        http_client = create_http_client(cfg)
        embedding_http_client = create_http_client(
            cfg,
            profile=HttpClientProfile.EMBEDDING_BATCH,
        )
        embedding_client = EmbeddingClient(
            http_client=embedding_http_client,
            settings=cfg,
        )
    if with_redis:
        redis = create_redis_client(cfg)
    if with_milvus:
        milvus = create_milvus_client()

    resources = TaskResources(
        settings=cfg,
        engine=engine,
        sessionmaker=sessionmaker,
        http_client=http_client,
        embedding_http_client=embedding_http_client,
        embedding_client=embedding_client,
        redis=redis,
        milvus=milvus,
    )
    try:
        yield resources
    finally:
        await close_http_client(http_client)
        await close_http_client(embedding_http_client)
        await close_redis_client(redis)
        if milvus is not None:
            try:
                await milvus.aclose()
            except Exception:  # pragma: no cover - best effort
                pass
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:  # pragma: no cover - best effort
                pass
