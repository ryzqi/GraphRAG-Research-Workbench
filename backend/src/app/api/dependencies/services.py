from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, TypeAlias, TypeVar, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap.app_resources import AppResources
from app.api.dependencies.app_resources import AppResourcesDep
from app.api.deps import AsyncSessionDep
from app.db.session import create_sessionmaker, open_session_scope
from app.repositories.extension_repository import ExtensionRepository
from app.repositories.queue_health_repository import QueueHealthRepository
from app.repositories.research_session_repository import ResearchSessionRepository
from app.services.extension_service import ExtensionService
from app.services.export_service import ExportService
from app.services.general_chat_service import GeneralChatService
from app.services.index_rebuild_service import IndexRebuildService
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.kb_bootstrap_job_service import KBBootstrapJobService
from app.services.kb_chat_service import KbChatService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.material_service import MaterialService
from app.services.model_config_service import ModelConfigService
from app.services.public_runtime_config_service import PublicRuntimeConfigService
from app.services.queue_health_service import QueueHealthService
from app.services.research_service import ResearchService, build_research_service

_ServiceT = TypeVar("_ServiceT")


def build_general_chat_service(
    *,
    db: AsyncSessionDep,
    resources: AppResourcesDep,
) -> GeneralChatService:
    return GeneralChatService(
        db,
        resources.llm_client,
        redis=resources.redis,
        http_client=resources.http_client,
    )


def build_kb_chat_service(
    *,
    db: AsyncSessionDep,
    resources: AppResourcesDep,
) -> KbChatService:
    return KbChatService(
        db,
        resources.llm_client,
        resources.milvus_client,
        resources.embedding_client,
        reranker=resources.rerank_client,
        redis=resources.redis,
        semantic_cache_service=resources.semantic_cache_service,
    )


def get_research_service(
    *,
    db: AsyncSessionDep,
    request: Request,
    resources: AppResourcesDep,
) -> ResearchService:
    raw_factory = resources.research_service_factory
    if callable(raw_factory):
        return cast(ResearchService, raw_factory(db=db, request=request))
    return build_research_service(
        db=db,
        session_repository=ResearchSessionRepository(db),
    )


def build_queue_health_service(
    *,
    db: AsyncSessionDep,
    resources: AppResourcesDep,
) -> QueueHealthService:
    return QueueHealthService(
        db,
        redis=resources.redis,
        repository=QueueHealthRepository(db),
    )


def build_extension_service(*, db: AsyncSessionDep) -> ExtensionService:
    return ExtensionService(
        db,
        repository=ExtensionRepository(db),
    )


def build_export_service() -> ExportService:
    return ExportService()


def build_ingestion_batch_service(*, db: AsyncSessionDep) -> IngestionBatchService:
    return IngestionBatchService(db)


def build_kb_bootstrap_job_service(*, db: AsyncSessionDep) -> KBBootstrapJobService:
    return KBBootstrapJobService(db)


def build_knowledge_base_service(*, db: AsyncSessionDep) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)


def build_material_service(*, db: AsyncSessionDep) -> MaterialService:
    return MaterialService(db)


def build_model_config_service(*, db: AsyncSessionDep) -> ModelConfigService:
    return ModelConfigService(db)


def build_public_runtime_config_service() -> PublicRuntimeConfigService:
    return PublicRuntimeConfigService()


def build_index_rebuild_service(*, db: AsyncSessionDep) -> IndexRebuildService:
    return IndexRebuildService(db)


@asynccontextmanager
async def _open_service_scope(
    *,
    resources: AppResources,
    factory: Callable[[AsyncSession], _ServiceT],
) -> AsyncIterator[tuple[AsyncSession, _ServiceT]]:
    sessionmaker = create_sessionmaker(engine=resources.engine)
    async with open_session_scope(sessionmaker) as db:
        yield db, factory(db)


@asynccontextmanager
async def open_general_chat_service_scope(
    *,
    resources: AppResources,
) -> AsyncIterator[tuple[AsyncSession, GeneralChatService]]:
    async with _open_service_scope(
        resources=resources,
        factory=lambda db: build_general_chat_service(db=db, resources=resources),
    ) as scope:
        yield scope


@asynccontextmanager
async def open_kb_chat_service_scope(
    *,
    resources: AppResources,
) -> AsyncIterator[tuple[AsyncSession, KbChatService]]:
    async with _open_service_scope(
        resources=resources,
        factory=lambda db: build_kb_chat_service(db=db, resources=resources),
    ) as scope:
        yield scope


@asynccontextmanager
async def open_ingestion_batch_service_scope(
    *,
    resources: AppResources,
) -> AsyncIterator[tuple[AsyncSession, IngestionBatchService]]:
    async with _open_service_scope(
        resources=resources,
        factory=lambda db: build_ingestion_batch_service(db=db),
    ) as scope:
        yield scope


GeneralChatServiceDep: TypeAlias = Annotated[
    GeneralChatService, Depends(build_general_chat_service)
]
KbChatServiceDep: TypeAlias = Annotated[KbChatService, Depends(build_kb_chat_service)]
ResearchServiceDep: TypeAlias = Annotated[ResearchService, Depends(get_research_service)]
QueueHealthServiceDep: TypeAlias = Annotated[
    QueueHealthService, Depends(build_queue_health_service)
]
ExtensionServiceDep: TypeAlias = Annotated[
    ExtensionService, Depends(build_extension_service)
]
ExportServiceDep: TypeAlias = Annotated[ExportService, Depends(build_export_service)]
IngestionBatchServiceDep: TypeAlias = Annotated[
    IngestionBatchService, Depends(build_ingestion_batch_service)
]
KBBootstrapJobServiceDep: TypeAlias = Annotated[
    KBBootstrapJobService, Depends(build_kb_bootstrap_job_service)
]
KnowledgeBaseServiceDep: TypeAlias = Annotated[
    KnowledgeBaseService, Depends(build_knowledge_base_service)
]
MaterialServiceDep: TypeAlias = Annotated[
    MaterialService, Depends(build_material_service)
]
ModelConfigServiceDep: TypeAlias = Annotated[
    ModelConfigService, Depends(build_model_config_service)
]
PublicRuntimeConfigServiceDep: TypeAlias = Annotated[
    PublicRuntimeConfigService, Depends(build_public_runtime_config_service)
]
IndexRebuildServiceDep: TypeAlias = Annotated[
    IndexRebuildService, Depends(build_index_rebuild_service)
]
