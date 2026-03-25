"""处理 ingestion-batch 文档的 Celery 任务。"""

from __future__ import annotations

import asyncio
import logging
import uuid

from dataclasses import dataclass
from sqlalchemy import select

from app.core.errors import AppError
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.object_storage import ObjectStorage
from app.models.kb_config_snapshot import KBConfigSnapshot
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking import ChunkingEngine
from app.services.contextual_embedding_service import ContextualEmbeddingService
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.parsing import ParseError, parse_material
from app.services.query_dependent_collections import collection_name_for_window
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources
from app.worker.tasks.contextual_retry import generate_contexts_for_chunks
from app.worker.tasks.embedding_inputs import build_embedding_inputs


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ProcessingFailure(Exception):
    code: str
    message: str
    retryable: bool


@dataclass(slots=True)
class _DocProcessOutcome:
    chunk_count: int
    context_failed_chunks: list[dict]
    semantic_fallback_chunks: int


def _raise_on_embedding_count_mismatch(
    *,
    expected_count: int,
    actual_count: int,
    doc_id: str,
    material_id: str,
) -> None:
    if expected_count == actual_count:
        return
    logger.error(
        "Ingestion embedding count mismatch",
        extra={
            "doc_id": doc_id,
            "material_id": material_id,
            "embedding_input_count": expected_count,
            "embedding_output_count": actual_count,
        },
    )
    raise _ProcessingFailure(
        code="EMBEDDING_COUNT_MISMATCH",
        message=(
            "Embedding 返回数量与输入数量不一致: "
            f"expected={expected_count}, actual={actual_count}"
        ),
        retryable=True,
    )


def _build_parent_id_by_ref(*, chunk_items: list, chunk_ids: list[uuid.UUID]) -> dict[int, str]:
    parent_id_by_ref: dict[int, str] = {}
    parent_index = 0
    for idx, chunk_item in enumerate(chunk_items):
        if chunk_item.chunk_role == "parent":
            parent_id_by_ref[parent_index] = str(chunk_ids[idx])
            parent_index += 1
    return parent_id_by_ref


def _resolve_parent_chunk_id(*, chunk_item, parent_id_by_ref: dict[int, str]) -> str:
    if chunk_item.chunk_role == "child" and chunk_item.parent_ref is not None:
        return parent_id_by_ref.get(chunk_item.parent_ref, "")
    return ""


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
        if (
            size == chunk_size_tokens
            and overlap == chunk_overlap_tokens
        ):
            matched.append(record)
    return matched


async def _write_records_to_milvus(
    *,
    milvus,
    index_config: IndexConfig,
    base_collection: str,
    material_id: str,
    records: list[dict],
    embedding_dim: int | None,
) -> None:
    if (
        index_config.chunking.general_strategy
        == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE
    ):
        # 清理同一素材的旧单集合数据，避免检索结果混入过期内容。
        await milvus.delete_by_material(material_id)

        for window in index_config.chunking.query_dependent_multiscale.windows:
            collection_name = collection_name_for_window(
                base_collection,
                window.chunk_size_tokens,
                window.chunk_overlap_tokens,
            )
            if embedding_dim is not None:
                await milvus.ensure_collection(
                    dim=embedding_dim,
                    collection_name=collection_name,
                )
            await milvus.delete_by_material(
                material_id,
                collection_name=collection_name,
            )


            window_records = _records_for_window(
                records,
                chunk_size_tokens=window.chunk_size_tokens,
                chunk_overlap_tokens=window.chunk_overlap_tokens,
            )
            if window_records:
                await milvus.upsert_batch(
                    records=window_records,
                    collection_name=collection_name,
                )
        return

    if embedding_dim is not None:
        await milvus.ensure_collection(dim=embedding_dim)
    await milvus.delete_by_material(material_id)
    if records:
        await milvus.upsert_batch(records=records)


_RETRYABLE_PARSE_CODES = {
    "URL_FETCH_FAILED",
    "URL_FETCH_EXCEPTION",
    "URL_TOO_MANY_REDIRECTS",
    "MINERU_RUNTIME_ERROR",
    "MINERU_TIMEOUT",
    "MINERU_BAD_OUTPUT",
}


@celery_app.task(name="app.worker.tasks.ingestion_batches.run_ingestion_batch_doc")
def run_ingestion_batch_doc(doc_id: str) -> None:
    asyncio.run(_run_ingestion_batch_doc(doc_id))


async def _finalize_doc_on_app_error(
    *,
    service: IngestionBatchService,
    doc_id: uuid.UUID,
    error: AppError,
) -> None:
    await service.rollback()
    doc = await service.get_doc(doc_id=doc_id, for_update=True)
    if doc is None:
        return
    if doc.status.value == "completed":
        return

    await service.mark_doc_failed(
        doc=doc,
        error_code=error.code,
        error_message=error.message,
        retryable=False,
    )
    await service.recalculate_batch_for_doc(doc=doc, reason="doc_failed_app_error")
    await service.commit()


async def _run_ingestion_batch_doc(doc_id: str) -> None:
    settings = get_settings()
    doc_uuid = uuid.UUID(doc_id)

    async with managed_task_resources(
        settings=settings,
        with_engine=True,
        with_http=True,
        with_milvus=True,
    ) as resources:
        sessionmaker = resources.sessionmaker
        if sessionmaker is None:  # pragma: no cover
            return

        async with sessionmaker() as session:
            service = IngestionBatchService(session)
            doc = await service.get_doc(doc_id=doc_uuid, for_update=True)
            if doc is None:
                return
            batch = doc.batch
            if batch is not None and batch.status.value == "completed":
                return
            if doc.status.value == "completed":
                return

            try:
                await service.mark_doc_running(doc=doc)
                await service.recalculate_batch_for_doc(doc=doc, reason="doc_start")
                await service.commit()

                outcome = await _process_doc(doc=doc, resources=resources)
                await service.mark_doc_succeeded(
                    doc=doc,
                    chunk_count=outcome.chunk_count,
                    context_failed_chunks=outcome.context_failed_chunks,
                )
                if outcome.semantic_fallback_chunks > 0:
                    logger.warning(
                        "Semantic chunking fallback detected during ingestion",
                        extra={
                            "doc_id": str(doc.id),
                            "kb_id": str(doc.kb_id),
                            "semantic_fallback_chunks": outcome.semantic_fallback_chunks,
                        },
                    )
                await service.recalculate_batch_for_doc(doc=doc, reason="doc_succeeded")
                await service.commit()
            except _ProcessingFailure as failure:
                await service.rollback()
                doc = await service.get_doc(doc_id=doc_uuid, for_update=True)
                if doc is None:
                    return

                delay = await service.mark_doc_failed(
                    doc=doc,
                    error_code=failure.code,
                    error_message=failure.message,
                    retryable=failure.retryable,
                )
                await service.recalculate_batch_for_doc(doc=doc, reason="doc_failed")
                await service.commit()

                if delay is not None:
                    run_ingestion_batch_doc.apply_async(args=[str(doc.id)], countdown=delay)
            except AppError as exc:
                logger.warning(
                    "Ingestion doc processing hit AppError",
                    extra={
                        "doc_id": str(doc_uuid),
                        "error_code": exc.code,
                        "error_message": exc.message,
                    },
                )
                await _finalize_doc_on_app_error(
                    service=service,
                    doc_id=doc_uuid,
                    error=exc,
                )
            except Exception as exc:  # pragma: no cover - defensive fallback
                await service.rollback()
                doc = await service.get_doc(doc_id=doc_uuid, for_update=True)
                if doc is None:
                    return
                delay = await service.mark_doc_failed(
                    doc=doc,
                    error_code="DOC_PROCESSING_ERROR",
                    error_message=str(exc),
                    retryable=True,
                )
                await service.recalculate_batch_for_doc(doc=doc, reason="doc_failed")
                await service.commit()
                if delay is not None:
                    run_ingestion_batch_doc.apply_async(args=[str(doc.id)], countdown=delay)


async def _process_doc(*, doc, resources) -> _DocProcessOutcome:
    if not doc.source_ref:
        raise _ProcessingFailure(
            code="DOC_SOURCE_REF_MISSING",
            message="文档 source_ref 为空，无法处理",
            retryable=False,
        )

    try:
        material_id = uuid.UUID(str(doc.source_ref))
    except ValueError as exc:
        raise _ProcessingFailure(
            code="DOC_SOURCE_REF_INVALID",
            message="文档 source_ref 不是有效 UUID",
            retryable=False,
        ) from exc

    sessionmaker = resources.sessionmaker
    if sessionmaker is None:  # pragma: no cover
        raise _ProcessingFailure("SYSTEM_ERROR", "缺少 DB 资源", False)

    async with sessionmaker() as session:
        material = await session.get(SourceMaterial, material_id)
        if material is None:
            raise _ProcessingFailure(
                code="DOC_MATERIAL_NOT_FOUND",
                message="关联资料不存在",
                retryable=False,
            )

        kb = await session.get(KnowledgeBase, doc.kb_id)
        if kb is None:
            raise _ProcessingFailure("KB_NOT_FOUND", "知识库不存在", retryable=False)

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

        try:
            parsed = await parse_material(
                material,
                settings=get_settings(),
                http_client=resources.http_client,
                storage=ObjectStorage(),
            )
        except ParseError as exc:
            raise _ProcessingFailure(
                code=exc.error_code,
                message=exc.message,
                retryable=exc.error_code in _RETRYABLE_PARSE_CODES,
            ) from exc
        except Exception as exc:
            raise _ProcessingFailure(
                code="DOC_PARSE_EXCEPTION",
                message=str(exc),
                retryable=True,
            ) from exc

        parse_metadata = parsed.metadata if isinstance(parsed.metadata, dict) else {}
        logger.info(
            "Ingestion parse completed",
            extra={
                "doc_id": str(doc.id),
                "kb_id": str(doc.kb_id),
                "material_id": str(material.id),
                "source_type": material.source_type.value,
                "pdf_parse_path": parse_metadata.get("pdf_parse_path"),
                "fallback_used": bool(parse_metadata.get("fallback_used", False)),
                "mineru_block_count": parse_metadata.get("mineru_block_count"),
                "output_text_chars": len((parsed.text or "").strip()),
            },
        )

        embedding_client = resources.embedding_client or EmbeddingClient(
            http_client=resources.embedding_http_client,
            settings=get_settings(),
        )
        chunker = ChunkingEngine(settings=get_settings(), embedding=embedding_client)
        context_service = ContextualEmbeddingService(settings=get_settings())
        chunk_items = await chunker.split(parsed, index_config)
        semantic_fallback_chunks = sum(
            1
            for item in chunk_items
            if isinstance(item.metadata, dict) and item.metadata.get("semantic_fallback") is True
        )
        if not chunk_items:
            raise _ProcessingFailure(
                code="DOC_CHUNK_EMPTY",
                message="解析后未生成分块",
                retryable=False,
            )
        logger.info(
            "Ingestion chunking completed",
            extra={
                "doc_id": str(doc.id),
                "kb_id": str(doc.kb_id),
                "material_id": str(material.id),
                "output_chunk_count": len(chunk_items),
            },
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

        embedding_inputs = build_embedding_inputs(
            chunk_items=chunk_items,
            contexts=contexts,
            contextual_enabled=index_config.contextual.enabled,
        )

        embeddings: list[list[float]] = []
        batch_size = max(get_settings().ingestion_embedding_batch_size, 1)
        for start in range(0, len(embedding_inputs), batch_size):
            payload = embedding_inputs[start : start + batch_size]
            embeddings.extend(await embedding_client.embed(texts=payload))
        _raise_on_embedding_count_mismatch(
            expected_count=len(embedding_inputs),
            actual_count=len(embeddings),
            doc_id=str(doc.id),
            material_id=str(material.id),
        )

        milvus = resources.milvus
        if milvus is None:
            raise _ProcessingFailure("MILVUS_UNAVAILABLE", "Milvus 客户端不可用", True)

        chunk_store = ChunkPersistenceService(session)
        chunk_ids = [uuid.uuid4() for _ in chunk_items]
        context_failed_chunks = [
            {
                "chunk_index": idx,
                "attempts": result.attempts,
                "reason": result.error or "context_generation_failed",
            }
            for idx, result in enumerate(context_results)
            if result.status == "fallback"
        ]

        try:
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
            parent_id_by_ref = _build_parent_id_by_ref(
                chunk_items=chunk_items,
                chunk_ids=chunk_ids,
            )

            records: list[dict] = []
            for idx, (chunk_item, emb) in enumerate(zip(chunk_items, embeddings, strict=True)):
                chunk_meta = chunk_item.metadata if isinstance(chunk_item.metadata, dict) else {}
                records.append(
                    {
                        "chunk_id": str(chunk_ids[idx]),
                        "kb_id": str(material.kb_id),
                        "material_id": str(material.id),
                        "chunk_role": chunk_item.chunk_role,
                        "parent_chunk_id": _resolve_parent_chunk_id(
                            chunk_item=chunk_item,
                            parent_id_by_ref=parent_id_by_ref,
                        ),
                        "child_seq": chunk_item.child_seq or 0,
                        "content": chunk_item.content,
                        "context": contexts[idx] if contexts else "",
                        "locator": chunk_item.locator or {},
                        "window_id": chunk_meta.get("window_id"),
                        "window_size_tokens": chunk_meta.get("window_size_tokens"),
                        "window_overlap_tokens": chunk_meta.get("window_overlap_tokens"),
                        "token_start": chunk_meta.get("token_start"),
                        "token_end": chunk_meta.get("token_end"),
                        "metadata": chunk_meta,
                        "dense_vector": emb,
                    }
                )

            await _write_records_to_milvus(
                milvus=milvus,
                index_config=index_config,
                base_collection=get_settings().milvus_collection,
                material_id=str(material.id),
                records=records,
                embedding_dim=len(embeddings[0]) if embeddings else None,
            )
            await session.commit()
            return _DocProcessOutcome(
                chunk_count=len(records),
                context_failed_chunks=context_failed_chunks,
                semantic_fallback_chunks=semantic_fallback_chunks,
            )
        except Exception:
            await session.rollback()
            raise
