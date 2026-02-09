"""Celery tasks for ingestion-batch document processing."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from app.core.errors import AppError
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.object_storage import ObjectStorage
from app.models.knowledge_base import KnowledgeBase
from app.models.source_material import SourceMaterial
from app.schemas.knowledge_bases import IndexConfig
from app.services.chunk_persistence_service import ChunkPersistenceService
from app.services.chunking import ChunkingEngine
from app.services.contextual_embedding_service import ContextualEmbeddingService
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.parsing import ParseError, parse_material
from app.worker.celery_app import celery_app
from app.worker.task_resources import managed_task_resources
from app.worker.tasks.embedding_inputs import build_embedding_inputs


@dataclass(slots=True)
class _ProcessingFailure(Exception):
    code: str
    message: str
    retryable: bool


_RETRYABLE_PARSE_CODES = {
    "URL_FETCH_FAILED",
    "URL_FETCH_EXCEPTION",
    "URL_TOO_MANY_REDIRECTS",
}


@celery_app.task(name="app.worker.tasks.ingestion_batches.run_ingestion_batch_doc")
def run_ingestion_batch_doc(doc_id: str) -> None:
    asyncio.run(_run_ingestion_batch_doc(doc_id))


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
            if batch is not None and batch.status.value == "canceled":
                return
            if doc.status.value == "canceled":
                return

            try:
                await service.mark_doc_running(doc=doc)
                await service.commit()

                chunk_count = await _process_doc(doc=doc, resources=resources)
                await service.mark_doc_succeeded(doc=doc, chunk_count=chunk_count)
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
            except AppError:
                await service.rollback()
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


async def _process_doc(*, doc, resources) -> int:
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

        index_config = IndexConfig.model_validate(kb.index_config or {})

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

        embedding_client = EmbeddingClient(http_client=resources.http_client)
        chunker = ChunkingEngine(settings=get_settings(), embedding=embedding_client)
        context_service = ContextualEmbeddingService(settings=get_settings())
        chunk_items = await chunker.split(parsed, index_config)
        if not chunk_items:
            raise _ProcessingFailure(
                code="DOC_CHUNK_EMPTY",
                message="解析后未生成分块",
                retryable=False,
            )

        contexts = ["" for _ in chunk_items]
        if index_config.contextual.enabled:
            semaphore = asyncio.Semaphore(max(index_config.contextual.concurrency, 1))

            async def _generate_context(text: str) -> str:
                async with semaphore:
                    result = await context_service.generate(
                        full_text=parsed.text or "",
                        chunk=text,
                        enabled=index_config.contextual.enabled,
                        max_tokens=index_config.contextual.max_tokens,
                    )
                    return result.context if result.success else ""

            contexts = await asyncio.gather(*[_generate_context(item.content) for item in chunk_items])

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

        milvus = resources.milvus
        if milvus is None:
            raise _ProcessingFailure("MILVUS_UNAVAILABLE", "Milvus 客户端不可用", True)

        if embeddings:
            await milvus.ensure_collection(dim=len(embeddings[0]))

        chunk_store = ChunkPersistenceService(session)
        chunk_ids = [uuid.uuid4() for _ in chunk_items]

        try:
            await milvus.delete_by_material(str(material.id))

            chunk_ids = await chunk_store.replace_material_chunks(
                kb_id=material.kb_id,
                material_id=material.id,
                chunk_items=chunk_items,
                chunk_ids=chunk_ids,
                processed_texts=embedding_inputs,
            )

            records: list[dict] = []
            for idx, (chunk_item, emb) in enumerate(zip(chunk_items, embeddings, strict=False)):
                records.append(
                    {
                        "chunk_id": str(chunk_ids[idx]),
                        "kb_id": str(material.kb_id),
                        "material_id": str(material.id),
                        "chunk_role": chunk_item.chunk_role,
                        "parent_chunk_id": "",
                        "child_seq": chunk_item.child_seq or 0,
                        "content": chunk_item.content,
                        "context": contexts[idx] if contexts else "",
                        "locator": chunk_item.locator or {},
                        "metadata": chunk_item.metadata or {},
                        "dense_vector": emb,
                    }
                )

            await milvus.upsert_batch(records=records)
            await session.commit()
            return len(records)
        except Exception:
            await session.rollback()
            raise
