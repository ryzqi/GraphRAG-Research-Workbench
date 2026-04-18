from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.bootstrap.app_resources import AppResources, require_app_resources, set_app_resources
from app.core.checkpoint import CheckpointManager
from app.core.memory_store import StoreManager
from app.core.settings import Settings, validate_startup_settings
from app.db.schema_guard import ensure_ingestion_schema_ready
from app.db.session import get_engine, get_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.http_client import (
    HttpClientProfile,
    close_http_client,
    create_http_client,
)
from app.integrations.langgraph_postgres_pool import LangGraphPostgresPool
from app.integrations.llm_client import LLMClient
from app.integrations.model_runtime_config import ModelRuntimeConfigManager
from app.integrations.milvus_client import create_milvus_client
from app.integrations.redis_client import close_redis_client, create_redis_client
from app.integrations.rerank_client import RerankClient
from app.services.semantic_cache.service import KbChatSemanticCacheService
from app.services.agent_run_recovery import (
    recover_stale_interactive_agent_runs_on_startup,
)

logger = logging.getLogger(__name__)


async def _initialize_app_state(app: FastAPI, settings: Settings) -> None:
    validate_startup_settings(settings)
    sessionmaker = get_sessionmaker()
    engine = get_engine()
    await ensure_ingestion_schema_ready(engine)
    await ModelRuntimeConfigManager.initialize(
        sessionmaker=sessionmaker,
        settings=settings,
    )
    await recover_stale_interactive_agent_runs_on_startup(
        sessionmaker=sessionmaker,
        settings=settings,
    )
    await LangGraphPostgresPool.initialize(settings)
    await CheckpointManager.initialize()
    await StoreManager.initialize()
    http_client = create_http_client(settings)
    embedding_http_client = create_http_client(
        settings,
        profile=HttpClientProfile.EMBEDDING_REALTIME,
    )
    llm_client = LLMClient(http_client=http_client)
    embedding_client = EmbeddingClient(
        http_client=embedding_http_client,
        settings=settings,
    )
    semantic_cache_service = KbChatSemanticCacheService(
        embedding=embedding_client,
        settings=settings,
    )
    rerank_client = RerankClient(
        settings=settings,
        http_client=http_client,
    )
    set_app_resources(
        app,
        AppResources(
            engine=engine,
            http_client=http_client,
            embedding_http_client=embedding_http_client,
            llm_client=llm_client,
            milvus_client=create_milvus_client(),
            embedding_client=embedding_client,
            rerank_client=rerank_client,
            redis=create_redis_client(settings),
            semantic_cache_service=semantic_cache_service,
        ),
    )


async def _shutdown_app_state(app: FastAPI) -> None:
    resources = require_app_resources(app)
    try:
        await close_http_client(resources.http_client)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("HTTP client 关闭失败", extra={"error": str(exc)})
    try:
        await close_http_client(resources.embedding_http_client)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Embedding HTTP client 关闭失败", extra={"error": str(exc)})
    try:
        await resources.milvus_client.aclose()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Milvus client 关闭失败", extra={"error": str(exc)})
    try:
        await close_redis_client(resources.redis)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Redis client 关闭失败", extra={"error": str(exc)})
    try:
        await resources.engine.dispose()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("AsyncEngine dispose 失败", extra={"error": str(exc)})
    try:
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("清理 DB 缓存失败", extra={"error": str(exc)})
    try:
        await ModelRuntimeConfigManager.shutdown()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("模型运行时配置关闭失败", extra={"error": str(exc)})
    await StoreManager.shutdown()
    await CheckpointManager.shutdown()
    await LangGraphPostgresPool.shutdown()


def create_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await _initialize_app_state(app, settings)
        yield
        await _shutdown_app_state(app)

    return lifespan
