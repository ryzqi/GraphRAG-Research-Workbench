"""Index rebuild job worker."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.settings import get_settings
from app.db.session import get_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.http_client import create_http_client
from app.integrations.milvus_client import get_milvus_client
from app.integrations.object_storage import ObjectStorage
from app.models.index_rebuild_job import IndexRebuildJob, IndexRebuildStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial
from app.schemas.knowledge_bases import IndexConfig
from app.services.chunking import ChunkingEngine
from app.services.contextual_embedding_service import ContextualEmbeddingService
from app.services.parsing import ParseError, parse_material
from app.worker.celery_app import celery_app


@celery_app.task(name="app.worker.tasks.index_rebuild.run_index_rebuild_job")
def run_index_rebuild_job(job_id: str) -> None:
    """Celery entrypoint for index rebuild."""
    asyncio.run(_run_index_rebuild_job(job_id))


async def _run_index_rebuild_job(job_id: str) -> None:
    sessionmaker = get_sessionmaker()
    job_uuid = uuid.UUID(job_id)

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
            "errors": [],
            "warnings": [],
        }

        try:
            settings = get_settings()
            milvus_client = get_milvus_client()
            http_client = create_http_client(settings)

            try:
                embedding_client = EmbeddingClient(http_client=http_client)
                chunker = ChunkingEngine(settings=settings, embedding=embedding_client)
                context_service = ContextualEmbeddingService(settings=settings)
                embedding_dim = settings.embedding_dim
                collection_ready = False

                if embedding_dim:
                    await milvus_client.ensure_collection(dim=embedding_dim)
                    collection_ready = True

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

                index_config = IndexConfig.model_validate(kb.index_config or {})

                # Clear old vectors for this KB
                await milvus_client.delete_by_kb_id(str(job.kb_id))
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
                        continue

                    contexts = ["" for _ in chunk_items]
                    if index_config.contextual.enabled:
                        concurrency = max(index_config.contextual.concurrency, 1)
                        semaphore = asyncio.Semaphore(concurrency)

                        async def _generate_context(chunk_text: str):
                            async with semaphore:
                                return await context_service.generate(
                                    full_text=parsed.text or "",
                                    chunk=chunk_text,
                                    enabled=index_config.contextual.enabled,
                                    timeout_seconds=index_config.contextual.timeout_seconds,
                                    max_tokens=index_config.contextual.max_tokens,
                                )

                        results = await asyncio.gather(
                            *[_generate_context(item.content) for item in chunk_items],
                            return_exceptions=True,
                        )
                        for idx, result in enumerate(results):
                            if isinstance(result, Exception):
                                continue
                            if result.success:
                                contexts[idx] = result.context

                    parent_content_by_ref: dict[int, str] = {}
                    parent_idx = 0
                    for item in chunk_items:
                        if item.chunk_role == "parent":
                            parent_content_by_ref[parent_idx] = item.content
                            parent_idx += 1

                    embedding_inputs: list[str] = []
                    for item, context in zip(chunk_items, contexts):
                        base_text = item.content
                        if item.chunk_role == "child" and item.parent_ref is not None:
                            parent_text = parent_content_by_ref.get(item.parent_ref)
                            if parent_text:
                                base_text = f"{parent_text}\n\n{item.content}"
                        if index_config.contextual.enabled and context:
                            embedding_inputs.append(f"{base_text}\n\n{context}")
                        else:
                            embedding_inputs.append(base_text)

                    batch_size = max(settings.ingestion_embedding_batch_size, 1)
                    embeddings: list[list[float]] = []
                    for start in range(0, len(embedding_inputs), batch_size):
                        batch = embedding_inputs[start : start + batch_size]
                        embeddings.extend(await embedding_client.embed(texts=batch))

                    if embedding_dim is None and embeddings:
                        embedding_dim = len(embeddings[0])
                    if not collection_ready and embedding_dim:
                        await milvus_client.ensure_collection(dim=embedding_dim)
                        collection_ready = True

                    milvus_chunk_ids: list[str] = []
                    milvus_upserted = False
                    try:
                        chunk_ids = [str(uuid.uuid4()) for _ in chunk_items]
                        parent_id_by_ref: dict[int, str] = {}
                        parent_idx = 0
                        for idx, chunk_item in enumerate(chunk_items):
                            if chunk_item.chunk_role == "parent":
                                parent_id_by_ref[parent_idx] = chunk_ids[idx]
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
                                    "chunk_id": chunk_ids[idx],
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

                        milvus_chunk_ids = chunk_ids
                        await milvus_client.upsert_batch(records=milvus_records)
                        milvus_upserted = True

                        stats["succeeded_materials"] += 1
                        stats["total_chunks"] += len(milvus_chunk_ids)

                    except Exception as exc:
                        if milvus_upserted and milvus_chunk_ids:
                            try:
                                await milvus_client.delete_by_chunk_ids(
                                    milvus_chunk_ids
                                )
                            except Exception as cleanup_exc:  # pragma: no cover
                                stats["warnings"].append(
                                    {
                                        "material_id": str(material.id),
                                        "stage": "milvus_rollback_cleanup",
                                        "error": str(cleanup_exc),
                                    }
                                )
                        stats["errors"].append(
                            {
                                "material_id": str(material.id),
                                "stage": "ingest",
                                "error": str(exc),
                            }
                        )
                        continue

            finally:
                await http_client.aclose()

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
