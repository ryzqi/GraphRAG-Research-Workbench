"""索引重建作业 worker。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar, cast

from sqlalchemy import delete, select

from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.models.document_chunk import DocumentChunk
from app.models.index_rebuild_job import IndexRebuildJob, IndexRebuildStatus
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking import ChunkingEngine
from app.services.contextual_embedding_service import ContextualEmbeddingService
from app.services.knowledge_base_service import touch_kb_updated_at
from app.services.parsing import ParseError, parse_material
from app.services.query_dependent_collections import collection_name_for_window
from app.worker.async_runtime import run_in_worker_async_runtime
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources
from app.worker.tasks.contextual_retry import generate_contexts_for_chunks
from app.worker.tasks.embedding_fanout import embed_inputs_with_concurrency
from app.worker.tasks.embedding_inputs import build_embedding_inputs

logger = logging.getLogger(__name__)
_TMaterialResult = TypeVar("_TMaterialResult")


@dataclass(slots=True)
class _MaterialRebuildResult:
    succeeded: bool = False
    canceled: bool = False
    chunk_count: int = 0
    context_fallback_chunks: int = 0
    semantic_fallback_chunks: int = 0
    semantic_fallback_material: bool = False
    error: dict[str, Any] | None = None
    warnings: list[dict[str, str]] = field(default_factory=list)


class _IndexRebuildMaterialCanceled(Exception):
    """Material 级处理在作业取消后尽快停止，避免继续落库。"""


def _should_skip_index_rebuild_status(status: IndexRebuildStatus) -> bool:
    """仅排队中的作业允许进入重建执行阶段。"""
    return status is not IndexRebuildStatus.QUEUED


@celery_app.task(name="app.worker.tasks.index_rebuild.run_index_rebuild_job")
def run_index_rebuild_job(job_id: str) -> None:
    """索引重建的 Celery 入口。"""
    run_in_worker_async_runtime(_run_index_rebuild_job(job_id))


def _raise_on_index_rebuild_embedding_count_mismatch(
    *,
    expected_count: int,
    actual_count: int,
    job_id: str,
    material_id: str,
) -> None:
    if expected_count == actual_count:
        return
    logger.error(
        "Index rebuild embedding count mismatch",
        extra={
            "job_id": job_id,
            "material_id": material_id,
            "embedding_input_count": expected_count,
            "embedding_output_count": actual_count,
        },
    )
    raise RuntimeError(
        f"EMBEDDING_COUNT_MISMATCH: expected={expected_count}, actual={actual_count}"
    )


def _records_for_window(
    records: list[dict],
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
) -> list[dict]:
    matched: list[dict] = []
    for record in records:
        size = record.get("window_size_tokens")
        overlap = record.get("window_overlap_tokens")
        if size == chunk_size_tokens and overlap == chunk_overlap_tokens:
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
    if (
        index_config.chunking.general_strategy
        == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
    ):
        collections: list[str] = []

        # 清理旧单集合数据，避免迁移后检索结果混杂。
        await milvus_client.delete_by_kb_id(kb_id)

        for window in index_config.chunking.query_dependent_multiscale.windows:
            collection_name = collection_name_for_window(
                base_collection,
                window.chunk_size_tokens,
                window.chunk_overlap_tokens,
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
    if (
        index_config.chunking.general_strategy
        == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
    ):
        upserted_collections: list[str] = []
        for window in index_config.chunking.query_dependent_multiscale.windows:
            collection_name = collection_name_for_window(
                base_collection,
                window.chunk_size_tokens,
                window.chunk_overlap_tokens,
            )
            if embedding_dim is not None:
                await milvus_client.ensure_collection(
                    dim=embedding_dim,
                    collection_name=collection_name,
                )
            window_records = _records_for_window(
                records,
                chunk_size_tokens=window.chunk_size_tokens,
                chunk_overlap_tokens=window.chunk_overlap_tokens,
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


async def _process_materials_with_sessions(
    *,
    materials: Sequence[SourceMaterial],
    sessionmaker: Any,
    concurrency: int,
    processor: Callable[[SourceMaterial, Any], Awaitable[_TMaterialResult]],
    cancel_event: asyncio.Event | None = None,
) -> list[_TMaterialResult]:
    if not materials:
        return []

    semaphore = asyncio.Semaphore(max(int(concurrency), 1))

    async def _worker(material: SourceMaterial) -> _TMaterialResult | None:
        async with semaphore:
            if cancel_event is not None and cancel_event.is_set():
                return None
            async with sessionmaker() as material_session:
                return await processor(material, material_session)

    results = await asyncio.gather(*[_worker(material) for material in materials])
    return [result for result in results if result is not None]


async def _watch_index_rebuild_cancellation(
    *,
    sessionmaker: Any,
    job_id: uuid.UUID,
    cancel_event: asyncio.Event,
    stop_event: asyncio.Event,
    poll_interval_seconds: float = 0.5,
) -> None:
    while not stop_event.is_set():
        async with sessionmaker() as monitor_session:
            job = await monitor_session.get(IndexRebuildJob, job_id)
            if job is None or job.status == IndexRebuildStatus.CANCELED:
                cancel_event.set()
                return

        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=max(poll_interval_seconds, 0.1)
            )
        except asyncio.TimeoutError:
            continue


def _raise_if_material_rebuild_canceled(
    cancel_event: asyncio.Event | None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _IndexRebuildMaterialCanceled


async def _cleanup_material_milvus_records(
    *,
    material_id: str,
    milvus_client: Any,
    milvus_chunk_ids: Sequence[str],
    upserted_collections: Sequence[str],
    warnings: list[dict[str, str]],
) -> None:
    if not milvus_chunk_ids or not upserted_collections:
        return
    try:
        for collection_name in upserted_collections:
            await milvus_client.delete_by_chunk_ids(
                list(milvus_chunk_ids),
                collection_name=collection_name,
            )
    except Exception as cleanup_exc:  # pragma: no cover
        warnings.append(
            {
                "material_id": material_id,
                "stage": "milvus_rollback_cleanup",
                "error": str(cleanup_exc),
            }
        )


async def _process_index_rebuild_material(
    *,
    material: SourceMaterial,
    material_session: Any,
    settings,
    job_id: str,
    index_config: IndexConfig,
    http_client: Any,
    storage: Any,
    url_crawler_source: Any,
    embedding_client: EmbeddingClient,
    chunker: ChunkingEngine,
    context_service: ContextualEmbeddingService,
    milvus_client: Any,
    base_collection: str,
    initial_embedding_dim: int | None,
    cancel_event: asyncio.Event | None = None,
) -> _MaterialRebuildResult:
    chunk_store = ChunkPersistenceService(material_session)
    if callable(url_crawler_source):
        url_crawler = await cast(Any, url_crawler_source)()
    else:
        url_crawler = url_crawler_source

    try:
        _raise_if_material_rebuild_canceled(cancel_event)
        parsed = await parse_material(
            material,
            settings=settings,
            http_client=http_client,
            storage=storage,
            url_crawler=url_crawler,
            allow_crawl4ai_cold_start=False,
        )
    except ParseError as exc:
        return _MaterialRebuildResult(
            error={
                "material_id": str(material.id),
                "stage": "parse",
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            }
        )
    except Exception as exc:
        return _MaterialRebuildResult(
            error={
                "material_id": str(material.id),
                "stage": "parse",
                "error_code": "PARSE_FAILED",
                "message": str(exc),
            }
        )

    semantic_fallback_chunks = 0
    context_fallback_chunks = 0
    warnings: list[dict[str, str]] = []
    milvus_chunk_ids: list[str] = []
    upserted_collections: list[str] = []
    milvus_upserted = False

    try:
        _raise_if_material_rebuild_canceled(cancel_event)
        chunk_items = await chunker.split(parsed, index_config)
        _raise_if_material_rebuild_canceled(cancel_event)
        if not chunk_items:
            await chunk_store.replace_material_chunks(
                kb_id=material.kb_id,
                material_id=material.id,
                chunk_items=[],
            )
            _raise_if_material_rebuild_canceled(cancel_event)
            await material_session.commit()
            return _MaterialRebuildResult()

        semantic_fallback_chunks = sum(
            1
            for item in chunk_items
            if isinstance(item.metadata, dict)
            and item.metadata.get("semantic_fallback") is True
        )

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
        context_fallback_chunks = sum(
            1 for item in context_results if item.status == "fallback"
        )
        _raise_if_material_rebuild_canceled(cancel_event)

        embedding_inputs = build_embedding_inputs(
            chunk_items=chunk_items,
            contexts=contexts,
            contextual_enabled=index_config.contextual.enabled,
        )

        batch_size = max(settings.ingestion_embedding_batch_size, 1)
        max_batch_size = settings.embedding_max_batch_size
        if max_batch_size is not None:
            batch_size = min(batch_size, max(int(max_batch_size), 1))
        embeddings = await embed_inputs_with_concurrency(
            embedding_client=embedding_client,
            embedding_inputs=embedding_inputs,
            batch_size=batch_size,
            fanout_concurrency=settings.ingestion_embedding_fanout_concurrency,
        )
        _raise_on_index_rebuild_embedding_count_mismatch(
            expected_count=len(embedding_inputs),
            actual_count=len(embeddings),
            job_id=job_id,
            material_id=str(material.id),
        )
        _raise_if_material_rebuild_canceled(cancel_event)

        embedding_dim = initial_embedding_dim
        if embedding_dim is None and embeddings:
            embedding_dim = len(embeddings[0])

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
        _raise_if_material_rebuild_canceled(cancel_event)

        parent_id_by_ref: dict[int, str] = {}
        parent_idx = 0
        for idx, chunk_item in enumerate(chunk_items):
            if chunk_item.chunk_role == "parent":
                parent_id_by_ref[parent_idx] = str(chunk_ids[idx])
                parent_idx += 1

        milvus_records: list[dict] = []
        for idx, (chunk_item, emb) in enumerate(
            zip(chunk_items, embeddings, strict=True)
        ):
            parent_chunk_id = ""
            if (
                chunk_item.chunk_role == "child"
                and chunk_item.parent_ref is not None
            ):
                parent_chunk_id = parent_id_by_ref.get(
                    chunk_item.parent_ref, ""
                )
            chunk_meta = (
                chunk_item.metadata if isinstance(chunk_item.metadata, dict) else {}
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
                    "window_id": chunk_meta.get("window_id"),
                    "window_size_tokens": chunk_meta.get("window_size_tokens"),
                    "window_overlap_tokens": chunk_meta.get(
                        "window_overlap_tokens"
                    ),
                    "token_start": chunk_meta.get("token_start"),
                    "token_end": chunk_meta.get("token_end"),
                    "metadata": chunk_meta,
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
        _raise_if_material_rebuild_canceled(cancel_event)
        await material_session.commit()

    except _IndexRebuildMaterialCanceled:
        if milvus_upserted:
            await _cleanup_material_milvus_records(
                material_id=str(material.id),
                milvus_client=milvus_client,
                milvus_chunk_ids=milvus_chunk_ids,
                upserted_collections=upserted_collections,
                warnings=warnings,
            )
        await material_session.rollback()
        return _MaterialRebuildResult(
            canceled=True,
            context_fallback_chunks=context_fallback_chunks,
            semantic_fallback_chunks=semantic_fallback_chunks,
            semantic_fallback_material=semantic_fallback_chunks > 0,
            warnings=warnings,
        )
    except Exception as exc:
        if milvus_upserted:
            await _cleanup_material_milvus_records(
                material_id=str(material.id),
                milvus_client=milvus_client,
                milvus_chunk_ids=milvus_chunk_ids,
                upserted_collections=upserted_collections,
                warnings=warnings,
            )
        await material_session.rollback()
        return _MaterialRebuildResult(
            context_fallback_chunks=context_fallback_chunks,
            semantic_fallback_chunks=semantic_fallback_chunks,
            semantic_fallback_material=semantic_fallback_chunks > 0,
            error={
                "material_id": str(material.id),
                "stage": "ingest",
                "error": str(exc),
            },
            warnings=warnings,
        )

    return _MaterialRebuildResult(
        succeeded=True,
        chunk_count=len(milvus_chunk_ids),
        context_fallback_chunks=context_fallback_chunks,
        semantic_fallback_chunks=semantic_fallback_chunks,
        semantic_fallback_material=semantic_fallback_chunks > 0,
    )


async def _run_index_rebuild_job(job_id: str) -> None:
    settings = get_settings()
    job_uuid = uuid.UUID(job_id)
    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_http=True,
        with_milvus=True,
        with_object_storage=True,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover - defensive
            return
        async with sessionmaker() as session:
            job = await session.get(IndexRebuildJob, job_uuid)
            if not job:
                return

            if _should_skip_index_rebuild_status(job.status):
                return

            job.status = IndexRebuildStatus.RUNNING
            job.error_message = None
            if job.started_at is None:
                job.started_at = datetime.now(timezone.utc)
            await session.commit()

            stats = {
                "total_materials": 0,
                "succeeded_materials": 0,
                "total_chunks": 0,
                "context_fallback_chunks": 0,
                "semantic_fallback_chunks": 0,
                "semantic_fallback_materials": 0,
                "errors": [],
                "warnings": [],
            }

            try:
                milvus_client = resources.milvus
                http_client = resources.http_client
                if milvus_client is None:  # pragma: no cover - defensive
                    return
                embedding_client = resources.embedding_client or EmbeddingClient(
                    http_client=resources.embedding_http_client,
                    settings=settings,
                )
                chunker = ChunkingEngine(settings=settings, embedding=embedding_client)
                context_service = ContextualEmbeddingService(settings=settings)
                initial_embedding_dim = settings.embedding_dim
                base_collection = settings.milvus_collection

                storage = resources.object_storage
                if storage is None:  # pragma: no cover - defensive
                    raise RuntimeError("共享 object_storage 未初始化")
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
                snapshot_config = (
                    await session.execute(snapshot_stmt)
                ).scalar_one_or_none()
                index_config = IndexConfig.model_validate(
                    snapshot_config or kb.index_config or {}
                )

                # 清理该知识库的旧向量与旧分块。
                await _prepare_rebuild_collections(
                    milvus_client=milvus_client,
                    index_config=index_config,
                    base_collection=base_collection,
                    kb_id=str(job.kb_id),
                    embedding_dim=initial_embedding_dim,
                )
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.kb_id == job.kb_id)
                )
                await session.commit()

                stmt = select(SourceMaterial).where(SourceMaterial.kb_id == job.kb_id)
                materials_result = await session.execute(stmt)
                materials = list(materials_result.scalars().all())
                stats["total_materials"] = len(materials)
                url_crawler_source = getattr(
                    resources,
                    "get_url_crawler",
                    getattr(resources, "url_crawler", None),
                )
                cancel_event = asyncio.Event()
                cancel_watch_stop = asyncio.Event()
                cancel_watch_task = asyncio.create_task(
                    _watch_index_rebuild_cancellation(
                        sessionmaker=sessionmaker,
                        job_id=job_uuid,
                        cancel_event=cancel_event,
                        stop_event=cancel_watch_stop,
                    )
                )
                try:
                    material_results = await _process_materials_with_sessions(
                        materials=materials,
                        sessionmaker=sessionmaker,
                        concurrency=settings.index_rebuild_material_concurrency,
                        processor=lambda material, material_session: _process_index_rebuild_material(
                            material=material,
                            material_session=material_session,
                            settings=settings,
                            job_id=str(job.id),
                            index_config=index_config,
                            http_client=http_client,
                            storage=storage,
                            url_crawler_source=url_crawler_source,
                            embedding_client=embedding_client,
                            chunker=chunker,
                            context_service=context_service,
                            milvus_client=milvus_client,
                            base_collection=base_collection,
                            initial_embedding_dim=initial_embedding_dim,
                            cancel_event=cancel_event,
                        ),
                        cancel_event=cancel_event,
                    )
                finally:
                    cancel_watch_stop.set()
                    await cancel_watch_task

                if cancel_event.is_set():
                    return

                for result in material_results:
                    stats["context_fallback_chunks"] += result.context_fallback_chunks
                    stats["semantic_fallback_chunks"] += result.semantic_fallback_chunks
                    if result.semantic_fallback_material:
                        stats["semantic_fallback_materials"] += 1
                    stats["warnings"].extend(result.warnings)
                    if result.error is not None:
                        stats["errors"].append(result.error)
                        continue
                    if result.succeeded:
                        stats["succeeded_materials"] += 1
                        stats["total_chunks"] += result.chunk_count

                job.status = (
                    IndexRebuildStatus.FAILED
                    if stats["errors"]
                    else IndexRebuildStatus.SUCCEEDED
                )
                if stats["errors"]:
                    job.error_message = "Index rebuild completed with errors"
                elif job.kb_id is not None:
                    await touch_kb_updated_at(session, job.kb_id)
                job.stats = stats
                job.finished_at = datetime.now(timezone.utc)

            except Exception as exc:
                job.status = IndexRebuildStatus.FAILED
                job.error_message = str(exc)
                job.stats = stats
                job.finished_at = datetime.now(timezone.utc)

            await session.commit()
