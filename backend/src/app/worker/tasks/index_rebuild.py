"""Index rebuild job worker."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.object_storage import ObjectStorage
from app.models.document_chunk import DocumentChunk
from app.models.index_rebuild_job import IndexRebuildJob, IndexRebuildStatus
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking import ChunkingEngine
from app.services.contextual_embedding_service import ContextualEmbeddingService
from app.services.parsing import ParseError, parse_material
from app.services.query_dependent_collections import collection_name_for_window
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources
from app.worker.tasks.contextual_retry import generate_contexts_for_chunks
from app.worker.tasks.embedding_inputs import build_embedding_inputs


@celery_app.task(name="app.worker.tasks.index_rebuild.run_index_rebuild_job")
def run_index_rebuild_job(job_id: str) -> None:
    """Celery entrypoint for index rebuild."""
    asyncio.run(_run_index_rebuild_job(job_id))


def _records_for_window(
    records: list[dict],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    matched: list[dict] = []
    for record in records:
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if (
            metadata.get("window_size") == chunk_size
            and metadata.get("window_overlap") == chunk_overlap
        ):
            matched.append(record)
    return matched


async def _prepare_rebuild_collections(
    *,
    milvus_client,
    index_config: IndexConfig,
    base_collection: str,
    kb_id: str,
    embedding_dim: int | None,
) -> list[str]:
    if index_config.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_CHUNKING:
        collections: list[str] = []
        for window in index_config.chunking.query_dependent_chunking.windows:
            collection_name = collection_name_for_window(
                base_collection,
                window.chunk_size,
                window.chunk_overlap,
            )
            if embedding_dim is not None:
                await milvus_client.ensure_collection(
                    dim=embedding_dim,
                    collection_name=collection_name,
                )
            await milvus_client.delete_by_kb_id(
                kb_id,
                collection_name=collection_name,
            )
            collections.append(collection_name)
        return collections

    if embedding_dim is not None:
        await milvus_client.ensure_collection(dim=embedding_dim)
    await milvus_client.delete_by_kb_id(kb_id)
    return [base_collection]


async def _upsert_rebuild_records(
    *,
    milvus_client,
    index_config: IndexConfig,
    base_collection: str,
    records: list[dict],
    embedding_dim: int | None,
) -> list[str]:
    if index_config.chunking.general_strategy == ChunkingStrategy.QUERY_DEPENDENT_CHUNKING:
        upserted_collections: list[str] = []
        for window in index_config.chunking.query_dependent_chunking.windows:
            collection_name = collection_name_for_window(
                base_collection,
                window.chunk_size,
                window.chunk_overlap,
            )
            if embedding_dim is not None:
                await milvus_client.ensure_collection(
                    dim=embedding_dim,
                    collection_name=collection_name,
                )
            window_records = _records_for_window(
                records,
                chunk_size=window.chunk_size,
                chunk_overlap=window.chunk_overlap,
            )
            if window_records:
                await milvus_client.upsert_batch(
                    records=window_records,
                    collection_name=collection_name,
                )
                upserted_collections.append(collection_name)
        return upserted_collections

    if not records:
        return []
    if embedding_dim is not None:
        await milvus_client.ensure_collection(dim=embedding_dim)
    await milvus_client.upsert_batch(records=records)
    return [base_collection]


async def _run_index_rebuild_job(job_id: str) -> None:
    settings = get_settings()
    job_uuid = uuid.UUID(job_id)
    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_http=True,
        with_milvus=True,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive
            return
        async with sessionmaker() as session:
            job = await session.get(IndexRebuildJob, job_uuid)
            if not job:
                return

            if job.status == IndexRebuildStatus.CANCELED:
                return

            job.status = IndexRebuildStatus.RUNNING
            if job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            await session.commit()

            stats = {
                "total_materials": 0,
                "succeeded_materials": 0,
                "total_chunks": 0,
                "context_fallback_chunks": 0,
                "errors": [],
                "warnings": [],
            }

            try:
                milvus_client = resources.milvus
                http_client = resources.http_client

                embedding_client = EmbeddingClient(http_client=http_client)
                chunker = ChunkingEngine(settings=settings, embedding=embedding_client)
                context_service = ContextualEmbeddingService(settings=settings)
                chunk_store = ChunkPersistenceService(session)
                embedding_dim = settings.embedding_dim
                base_collection = settings.milvus_collection

                storage = ObjectStorage()
                await storage.ensure_buckets()

                kb = await session.get(KnowledgeBase, job.kb_id)
                if not kb:
                    job.status = IndexRebuildStatus.FAILED
                    job.error_message = "knowledge base not found"
                    job.stats = stats
                    job.finished_at = datetime.now(timezone.utc)
                    await session.commit()
                    return

                snapshot_stmt = (
                    select(KBConfigSnapshot.config_json)
                    .where(
                        KBConfigSnapshot.kb_id == kb.id,
                        KBConfigSnapshot.is_active.is_(True),
                    )
                    .order_by(KBConfigSnapshot.version.desc())
                    .limit(1)
                )
                snapshot_config = (await session.execute(snapshot_stmt)).scalar_one_or_none()
                index_config = IndexConfig.model_validate(snapshot_config or kb.index_config or {})

                # Clear old vectors/chunks for this KB.
                await _prepare_rebuild_collections(
                    milvus_client=milvus_client,
                    index_config=index_config,
                    base_collection=base_collection,
                    kb_id=str(job.kb_id),
                    embedding_dim=embedding_dim,
                )
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.kb_id == job.kb_id)
                )
                await session.commit()

                stmt = select(SourceMaterial).where(SourceMaterial.kb_id == job.kb_id)
                materials_result = await session.execute(stmt)
                materials = list(materials_result.scalars().all())
                stats["total_materials"] = len(materials)

                for material in materials:
                    await session.refresh(job)
                    if job.status == IndexRebuildStatus.CANCELED:
                        return
                    await session.commit()

                    try:
                        parsed = await parse_material(
                            material,
                            settings=settings,
                            http_client=http_client,
                            storage=storage,
                        )
                    except ParseError as exc:
                        stats["errors"].append(
                            {
                                "material_id": str(material.id),
                                "stage": "parse",
                                "error_code": exc.error_code,
                                "message": exc.message,
                                "details": exc.details,
                            }
                        )
                        continue
                    except Exception as exc:
                        stats["errors"].append(
                            {
                                "material_id": str(material.id),
                                "stage": "parse",
                                "error_code": "PARSE_FAILED",
                                "message": str(exc),
                            }
                        )
                        continue

                    chunk_items = await chunker.split(parsed, index_config)
                    if not chunk_items:
                        await chunk_store.replace_material_chunks(
                            kb_id=material.kb_id,
                            material_id=material.id,
                            chunk_items=[],
                        )
                        await session.commit()
                        continue

                    context_results = await generate_contexts_for_chunks(
                        full_text=parsed.text or "",
                        chunk_texts=[item.content for item in chunk_items],
                        context_service=context_service,
                        enabled=index_config.contextual.enabled,
                        max_tokens=index_config.contextual.max_tokens,
                        concurrency=max(index_config.contextual.concurrency, 1),
                        max_attempts=3,
                    )
                    contexts = [item.context for item in context_results]
                    fallback_count = sum(1 for item in context_results if item.status == "fallback")
                    stats["context_fallback_chunks"] += fallback_count

                    embedding_inputs = build_embedding_inputs(
                        chunk_items=chunk_items,
                        contexts=contexts,
                        contextual_enabled=index_config.contextual.enabled,
                    )

                    batch_size = max(settings.ingestion_embedding_batch_size, 1)
                    embeddings: list[list[float]] = []
                    for start in range(0, len(embedding_inputs), batch_size):
                        batch = embedding_inputs[start : start + batch_size]
                        embeddings.extend(await embedding_client.embed(texts=batch))

                    if embedding_dim is None and embeddings:
                        embedding_dim = len(embeddings[0])

                    milvus_chunk_ids: list[str] = []
                    upserted_collections: list[str] = []
                    milvus_upserted = False
                    try:
                        chunk_ids = [uuid.uuid4() for _ in chunk_items]
                        chunk_ids = await chunk_store.replace_material_chunks(
                            kb_id=material.kb_id,
                            material_id=material.id,
                            chunk_items=chunk_items,
                            chunk_ids=chunk_ids,
                            embedding_texts=embedding_inputs,
                            context_texts=contexts,
                            context_statuses=[item.status for item in context_results],
                            context_errors=[item.error for item in context_results],
                            context_attempts=[item.attempts for item in context_results],
                        )

                        parent_id_by_ref: dict[int, str] = {}
                        parent_idx = 0
                        for idx, chunk_item in enumerate(chunk_items):
                            if chunk_item.chunk_role == "parent":
                                parent_id_by_ref[parent_idx] = str(chunk_ids[idx])
                                parent_idx += 1

                        milvus_records: list[dict] = []
                        for idx, (chunk_item, emb) in enumerate(
                            zip(chunk_items, embeddings, strict=False)
                        ):
                            parent_chunk_id = ""
                            if chunk_item.chunk_role == "child" and chunk_item.parent_ref is not None:
                                parent_chunk_id = parent_id_by_ref.get(
                                    chunk_item.parent_ref, ""
                                )
                            milvus_records.append(
                                {
                                    "chunk_id": str(chunk_ids[idx]),
                                    "kb_id": str(material.kb_id),
                                    "material_id": str(material.id),
                                    "chunk_role": chunk_item.chunk_role,
                                    "parent_chunk_id": parent_chunk_id,
                                    "child_seq": chunk_item.child_seq or 0,
                                    "content": chunk_item.content,
                                    "context": contexts[idx] if contexts else "",
                                    "locator": chunk_item.locator or {},
                                    "metadata": chunk_item.metadata or {},
                                    "dense_vector": emb,
                                }
                            )

                        milvus_chunk_ids = [str(cid) for cid in chunk_ids]
                        upserted_collections = await _upsert_rebuild_records(
                            milvus_client=milvus_client,
                            index_config=index_config,
                            base_collection=base_collection,
                            records=milvus_records,
                            embedding_dim=embedding_dim,
                        )
                        milvus_upserted = bool(upserted_collections)

                        stats["succeeded_materials"] += 1
                        stats["total_chunks"] += len(milvus_chunk_ids)
                        await session.commit()

                    except Exception as exc:
                        if milvus_upserted and milvus_chunk_ids:
                            try:
                                for collection_name in upserted_collections:
                                    await milvus_client.delete_by_chunk_ids(
                                        milvus_chunk_ids,
                                        collection_name=collection_name,
                                    )
                            except Exception as cleanup_exc:  # pragma: no cover
                                stats["warnings"].append(
                                    {
                                        "material_id": str(material.id),
                                        "stage": "milvus_rollback_cleanup",
                                        "error": str(cleanup_exc),
                                    }
                                )
                        await session.rollback()
                        stats["errors"].append(
                            {
                                "material_id": str(material.id),
                                "stage": "ingest",
                                "error": str(exc),
                            }
                        )
                        continue

                job.status = (
                    IndexRebuildStatus.FAILED
                    if stats["errors"]
                    else IndexRebuildStatus.SUCCEEDED
                )
                if stats["errors"]:
                    job.error_message = "Index rebuild completed with errors"
                job.stats = stats
                job.finished_at = datetime.now(timezone.utc)

            except Exception as exc:
                job.status = IndexRebuildStatus.FAILED
                job.error_message = str(exc)
                job.stats = stats
                job.finished_at = datetime.now(timezone.utc)

            await session.commit()
