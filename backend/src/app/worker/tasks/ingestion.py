"""导入任务 Celery 执行器（解析→切分→embedding→写 Postgres+Milvus）。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

from app.core.settings import get_settings
from app.db.session import get_sessionmaker
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.object_storage import ObjectRef, ObjectStorage
from app.models.document_chunk import DocumentChunk
from app.services.chunking import TextChunker
from app.services.contextual_embedding_service import ContextualEmbeddingService
from app.models.ingestion_job import (
    IngestionJob,
    IngestionJobItem,
    IngestionJobItemAction,
    IngestionStatus,
)
from app.models.source_material import SourceMaterial, SourceType
from app.worker.celery_app import celery_app
from app.utils.token_counter import count_tokens_approximately


@celery_app.task(name="app.worker.tasks.ingestion.run_ingestion_job")
def run_ingestion_job(job_id: str) -> None:
    """Celery 入口：执行导入任务。"""
    asyncio.run(_run_ingestion_job(job_id))


async def _run_ingestion_job(job_id: str) -> None:
    """异步执行导入任务。"""
    sessionmaker = get_sessionmaker()
    job_uuid = uuid.UUID(job_id)

    async with sessionmaker() as session:
        job = await session.get(IngestionJob, job_uuid)
        if not job:
            return

        # 检查是否已取消
        if job.status == IngestionStatus.CANCELED:
            return

        # 更新为运行中
        job.status = IngestionStatus.RUNNING
        await session.commit()

        stats = {"total_materials": 0, "total_chunks": 0, "errors": []}

        try:
            # 加载任务条目
            items: list[IngestionJobItem] = list(job.items)
            stats["total_materials"] = len(items)

            embedding_client = EmbeddingClient()
            milvus_client = MilvusClient()
            settings = get_settings()
            chunker = TextChunker(settings=settings, embedding=embedding_client)
            context_service = (
                ContextualEmbeddingService(settings=settings)
                if settings.ingestion_contextual_enabled
                else None
            )
            embedding_dim = settings.embedding_dim
            collection_ready = False

            if embedding_dim:
                await milvus_client.ensure_collection(dim=embedding_dim)
                collection_ready = True

            for item in items:
                # 重新检查取消状态
                await session.refresh(job)
                if job.status == IngestionStatus.CANCELED:
                    return

                try:
                    material = await session.get(SourceMaterial, item.material_id)
                    if not material:
                        stats["errors"].append(f"Material {item.material_id} not found")
                        continue

                    # 如果是更新模式，先删除旧的 chunks
                    if item.action == IngestionJobItemAction.UPDATE:
                        await _delete_material_chunks(
                            session, milvus_client, str(material.id)
                        )

                    # 获取资料内容
                    content = await _get_material_content(material)
                    if not content:
                        stats["errors"].append(
                            f"Material {material.id}: empty content"
                        )
                        continue

                    # 切分文本
                    chunks_text = await chunker.split(content)
                    if not chunks_text:
                        continue

                    contexts = ["" for _ in chunks_text]
                    if settings.ingestion_contextual_enabled and context_service:
                        for idx, chunk_text in enumerate(chunks_text):
                            context_result = await context_service.generate(
                                full_text=content, chunk=chunk_text
                            )
                            if context_result.success:
                                contexts[idx] = context_result.context
                            else:
                                contexts[idx] = ""

                    embedding_inputs = []
                    for chunk_text, context in zip(chunks_text, contexts):
                        if settings.ingestion_contextual_enabled and context:
                            embedding_inputs.append(f"{chunk_text}\n\n{context}")
                        else:
                            embedding_inputs.append(chunk_text)

                    # 批量生成 embedding
                    embeddings = await embedding_client.embed(texts=embedding_inputs)

                    if embedding_dim is None and embeddings:
                        embedding_dim = len(embeddings[0])
                    if not collection_ready and embedding_dim:
                        await milvus_client.ensure_collection(dim=embedding_dim)
                        collection_ready = True

                    # 写入 Postgres 和 Milvus
                    milvus_records = []
                    for idx, (text, emb) in enumerate(zip(chunks_text, embeddings)):
                        chunk = DocumentChunk(
                            kb_id=material.kb_id,
                            material_id=material.id,
                            chunk_index=idx,
                            text=text,
                            locator={"index": idx},
                            content_hash=hashlib.sha256(text.encode()).hexdigest()[:32],
                            token_count=count_tokens_approximately(text),
                        )
                        session.add(chunk)
                        await session.flush()

                        milvus_records.append(
                            {
                                "chunk_id": str(chunk.id),
                                "kb_id": str(material.kb_id),
                                "material_id": str(material.id),
                                "content": text,
                                "context": contexts[idx] if contexts else "",
                                "embedding": emb,
                            }
                        )
                        stats["total_chunks"] += 1

                    # 批量写入 Milvus
                    await milvus_client.upsert_batch(records=milvus_records)

                except Exception as e:
                    stats["errors"].append(f"Material {item.material_id}: {str(e)}")

            # 完成
            job.status = IngestionStatus.SUCCEEDED
            job.stats = stats

        except Exception as e:
            job.status = IngestionStatus.FAILED
            job.error_message = str(e)
            job.stats = stats

        await session.commit()


async def _get_material_content(material: SourceMaterial) -> str:
    """获取资料的文本内容。"""
    if material.source_type == SourceType.TEXT:
        # 文本资料：从 metadata 中获取
        text = (material.metadata_ or {}).get("text", "")
        return text or "[文本内容为空，占位]"

    elif material.source_type == SourceType.URL:
        # URL 资料：简单返回 URL（实际应抓取内容）
        # TODO: 实现 URL 内容抓取
        return f"[URL Content Placeholder: {material.uri or 'unknown'}]"

    elif material.source_type == SourceType.UPLOAD:
        # 上传文件：从 MinIO 获取
        if not material.uri or not material.uri.startswith("minio://"):
            return ""

        storage = ObjectStorage()
        await storage.ensure_buckets()
        # 解析 minio://bucket/object_name
        uri_parts = material.uri[8:].split("/", 1)
        if len(uri_parts) != 2:
            return ""

        bucket, object_name = uri_parts
        ref = ObjectRef(bucket=bucket, object_name=object_name)
        content_bytes = await storage.get_bytes(ref)

        # 简单处理：假设是文本文件
        # TODO: 根据 mime_type 使用不同解析器
        try:
            text = content_bytes.decode("utf-8", errors="ignore")
        except UnicodeDecodeError:
            text = ""
        return text or "[文件内容无法解码，占位]"

    return "[未能获取内容，占位]"


async def _delete_material_chunks(
    session, milvus_client: MilvusClient, material_id: str
) -> None:
    """删除资料的所有 chunks（Postgres + Milvus）。"""
    from sqlalchemy import delete

    # 删除 Postgres 中的 chunks
    stmt = delete(DocumentChunk).where(
        DocumentChunk.material_id == uuid.UUID(material_id)
    )
    await session.execute(stmt)

    # 删除 Milvus 中的向量
    await milvus_client.delete_by_material(material_id)
