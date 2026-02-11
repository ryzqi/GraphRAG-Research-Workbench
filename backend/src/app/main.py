from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.checkpoint import CheckpointManager
from app.core.deepagents_store import DeepAgentsStoreManager
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.memory_store import StoreManager
from app.core.middleware.request_id import RequestIdMiddleware
from app.core.settings import get_settings, validate_startup_settings
from app.db.schema_guard import ensure_ingestion_schema_ready
from app.db.session import get_engine, get_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.http_client import close_http_client, create_http_client
from app.integrations.llm_client import LLMClient
from app.integrations.milvus_client import create_milvus_client
from app.integrations.redis_client import close_redis_client, create_redis_client
from app.integrations.rerank_client import RerankClient

settings = get_settings()
configure_logging(settings.app_log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    validate_startup_settings(settings)
    app.state.engine = get_engine()
    await ensure_ingestion_schema_ready(app.state.engine)
    await CheckpointManager.initialize()
    await StoreManager.initialize()
    DeepAgentsStoreManager.initialize()
    app.state.http_client = create_http_client(settings)
    app.state.llm_client = LLMClient(http_client=app.state.http_client)
    app.state.embedding_client = EmbeddingClient(http_client=app.state.http_client)
    app.state.rerank_client = RerankClient(settings=settings, http_client=app.state.http_client)
    app.state.milvus_client = create_milvus_client()
    app.state.redis = create_redis_client(settings)
    yield
    try:
        await close_http_client(app.state.http_client)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("HTTP client 关闭失败", extra={"error": str(exc)})
    try:
        await app.state.milvus_client.aclose()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Milvus client 关闭失败", extra={"error": str(exc)})
    try:
        await close_redis_client(app.state.redis)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Redis client 关闭失败", extra={"error": str(exc)})
    try:
        await app.state.engine.dispose()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("AsyncEngine dispose 失败", extra={"error": str(exc)})
    try:
        get_engine.cache_clear()
        get_sessionmaker.cache_clear()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("清理 DB 缓存失败", extra={"error": str(exc)})
    DeepAgentsStoreManager.shutdown()
    await StoreManager.shutdown()
    await CheckpointManager.shutdown()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
)

app.include_router(api_router, prefix="/api/v1")
register_exception_handlers(app)
