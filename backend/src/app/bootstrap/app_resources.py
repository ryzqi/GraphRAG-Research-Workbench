from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.integrations.embedding_client import EmbeddingClient
from app.integrations.llm_client import LLMClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.object_storage import ObjectStorage
from app.integrations.redis_client import RedisClient
from app.integrations.rerank_client import RerankClient
from app.services.semantic_cache.service import KbChatSemanticCacheService

ResearchServiceFactory = Callable[..., object]


@dataclass(slots=True)
class AppResources:
    engine: AsyncEngine
    http_client: httpx.AsyncClient
    embedding_http_client: httpx.AsyncClient
    llm_client: LLMClient
    milvus_client: MilvusClient
    object_storage: ObjectStorage
    embedding_client: EmbeddingClient
    rerank_client: RerankClient
    redis: RedisClient
    semantic_cache_service: KbChatSemanticCacheService
    research_service_factory: ResearchServiceFactory | None = None


def set_app_resources(app: FastAPI, resources: AppResources) -> None:
    app.state.resources = resources


def require_app_resources(app: FastAPI) -> AppResources:
    resources = getattr(app.state, "resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("应用资源未初始化")
    return resources
