from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    checkpoints,
    chats,
    exports,
    extensions,
    health,
    ingestion_batches,
    index_rebuilds,
    kb_bootstrap_jobs,
    knowledge_bases,
    knowledge_updates,
    materials,
    model_config,
    research,
    system,
)

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(exports.router, prefix="/exports", tags=["Exports"])
api_router.include_router(
    knowledge_bases.router, prefix="/knowledge-bases", tags=["KnowledgeBases"]
)
api_router.include_router(chats.router, prefix="/chats", tags=["Chats"])
api_router.include_router(
    ingestion_batches.router, prefix="/ingestion-batches", tags=["IngestionBatches"]
)
api_router.include_router(
    index_rebuilds.router, prefix="/index-rebuilds", tags=["IndexRebuilds"]
)
api_router.include_router(materials.router, tags=["Materials"])
api_router.include_router(kb_bootstrap_jobs.router, tags=["KBBootstrapJobs"])
api_router.include_router(extensions.router, prefix="/extensions", tags=["Extensions"])
api_router.include_router(
    model_config.router, prefix="/model-config", tags=["ModelConfig"]
)
api_router.include_router(
    knowledge_updates.router, prefix="/knowledge-updates", tags=["KnowledgeUpdates"]
)
api_router.include_router(checkpoints.router, tags=["Checkpoints"])
api_router.include_router(research.router, prefix="/research", tags=["Research"])
api_router.include_router(system.router, tags=["System"])
