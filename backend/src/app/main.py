from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.checkpoint import CheckpointManager
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware.request_id import RequestIdMiddleware
from app.core.settings import get_settings, validate_startup_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.llm_client import LLMClient
from app.integrations.mcp_client import MCPClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.rerank_client import RerankClient

settings = get_settings()
configure_logging(settings.app_log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    validate_startup_settings(settings)
    await CheckpointManager.initialize()
    app.state.http_client = httpx.AsyncClient()
    app.state.llm_client = LLMClient(http_client=app.state.http_client)
    app.state.embedding_client = EmbeddingClient(http_client=app.state.http_client)
    app.state.rerank_client = RerankClient(settings=settings, http_client=app.state.http_client)
    app.state.milvus_client = MilvusClient()
    app.state.mcp_client = MCPClient()
    yield
    await app.state.mcp_client.close()
    await app.state.http_client.aclose()
    await CheckpointManager.shutdown()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Admin-Token"],
)

app.include_router(api_router, prefix="/api/v1")
register_exception_handlers(app)
