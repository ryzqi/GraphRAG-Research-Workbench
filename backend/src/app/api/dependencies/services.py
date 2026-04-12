from __future__ import annotations

from typing import Annotated, TypeAlias, cast

from fastapi import Depends, Request

from app.api.dependencies.app_resources import AppResourcesDep
from app.api.deps import AsyncSessionDep
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
from app.services.queue_health_service import QueueHealthService
from app.services.research_service import ResearchService, build_research_service


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
    return build_research_service(db=db)


def build_queue_health_service(
    *,
    db: AsyncSessionDep,
    resources: AppResourcesDep,
) -> QueueHealthService:
    return QueueHealthService(
        db,
        redis=resources.redis,
    )


def build_extension_service(*, db: AsyncSessionDep) -> ExtensionService:
    return ExtensionService(db)


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


def build_index_rebuild_service(*, db: AsyncSessionDep) -> IndexRebuildService:
    return IndexRebuildService(db)


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
IndexRebuildServiceDep: TypeAlias = Annotated[
    IndexRebuildService, Depends(build_index_rebuild_service)
]
