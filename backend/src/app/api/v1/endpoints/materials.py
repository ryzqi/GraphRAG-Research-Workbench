"""资料管理接口（列表/创建/上传）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.app_resources import AppResourcesDep
from app.api.dependencies.services import (
    IngestionBatchServiceDep,
    KnowledgeBaseServiceDep,
    MaterialServiceDep,
)
from app.integrations.object_storage import ObjectRef
from app.models.source_material import SourceType
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.schemas.materials import (
    DocumentChunkListResponse,
    DocumentChunkRead,
    MaterialCreateText,
    MaterialCreateUrl,
    MaterialListResponse,
    MaterialWithChunkStatsListResponse,
    MaterialWithChunkStatsRead,
    SourceMaterialRead,
)
from app.schemas.pagination import PageMeta
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.material_service import MaterialService

router = APIRouter()


def _extract_minio_object_ref(uri: str) -> ObjectRef:
    if not uri.startswith("minio://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_URI", "message": "UPLOAD 资料 uri 不是 minio://"},
        )

    uri_parts = uri[8:].split("/", 1)
    if len(uri_parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_URI", "message": "UPLOAD 资料 uri 格式非法"},
        )

    bucket, object_name = uri_parts
    if not bucket or not object_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_URI",
                "message": "UPLOAD 资料 uri 缺少 bucket/object_name",
            },
        )
    return ObjectRef(bucket=bucket, object_name=object_name)


def _material_filename_from_object_name(object_name: str) -> str:
    return object_name.split("/")[-1] if object_name else "download"


async def _ensure_kb_exists(
    kb_service: KnowledgeBaseService, kb_id: uuid.UUID
) -> None:
    kb = await kb_service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )


async def _ensure_material_in_kb(
    service: MaterialService,
    *,
    kb_id: uuid.UUID,
    material_id: uuid.UUID,
) -> None:
    material = await service.get_by_id(material_id)
    if material is None or material.kb_id != kb_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MATERIAL_NOT_FOUND", "message": "资料不存在"},
        )


async def _ensure_chunk_browsing_unlocked(
    ingestion_service: IngestionBatchService, *, kb_id: uuid.UUID
) -> None:
    active_batch = await ingestion_service.get_active_batch_for_kb(kb_id=kb_id)
    if active_batch is None:
        return

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "KB_INGESTION_IN_PROGRESS",
            "message": "文档处理中，待全部完成后再浏览",
            "details": {
                "batch_id": str(active_batch.id),
                "status": active_batch.status.value,
            },
        },
    )


@router.get(
    "/knowledge-bases/{kb_id}/materials",
    response_model=MaterialListResponse,
)
async def list_materials(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    kb_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> MaterialListResponse:
    """列出知识库下的所有资料。"""
    await _ensure_kb_exists(kb_service, kb_id)
    materials, total = await service.list_by_kb_page(kb_id, skip=skip, limit=limit)
    return MaterialListResponse(
        items=[SourceMaterialRead.model_validate(m) for m in materials],
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(materials)) < total,
        ),
    )


@router.get(
    "/knowledge-bases/{kb_id}/materials/with-chunk-stats",
    response_model=MaterialWithChunkStatsListResponse,
)
async def list_materials_with_chunk_stats(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    kb_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> MaterialWithChunkStatsListResponse:
    """列出知识库资料并附带分块统计。"""
    await _ensure_kb_exists(kb_service, kb_id)
    rows, total = await service.list_by_kb_with_chunk_stats_page(
        kb_id, skip=skip, limit=limit
    )
    items = [
        MaterialWithChunkStatsRead.model_validate(
            {
                **SourceMaterialRead.model_validate(material).model_dump(),
                "chunk_count": chunk_count,
            }
        )
        for material, chunk_count in rows
    ]
    return MaterialWithChunkStatsListResponse(
        items=items,
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(items)) < total,
        ),
    )


@router.get("/knowledge-bases/{kb_id}/materials/{material_id}/download")
async def download_material(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    resources: AppResourcesDep,
    kb_id: uuid.UUID,
    material_id: uuid.UUID,
) -> StreamingResponse:
    """流式下载上传型资料原始文件。"""
    await _ensure_kb_exists(kb_service, kb_id)
    material = await service.get_by_id(material_id)
    if material is None or material.kb_id != kb_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MATERIAL_NOT_FOUND", "message": "资料不存在"},
        )
    if material.source_type != SourceType.UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "MATERIAL_DOWNLOAD_UNSUPPORTED_SOURCE",
                "message": "仅上传型资料支持下载原始文件",
            },
        )
    if not material.uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_URI", "message": "UPLOAD 资料缺少 uri"},
        )

    ref = _extract_minio_object_ref(material.uri)
    filename = _material_filename_from_object_name(ref.object_name)
    storage = resources.object_storage
    await storage.ensure_buckets()
    if not await storage.exists(ref):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MATERIAL_FILE_NOT_FOUND", "message": "资料原文件不存在"},
        )
    return StreamingResponse(
        storage.iter_bytes(ref),
        media_type=material.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/knowledge-bases/{kb_id}/materials/{material_id}/chunks",
    response_model=DocumentChunkListResponse,
)
async def list_material_chunks(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    ingestion_service: IngestionBatchServiceDep,
    kb_id: uuid.UUID,
    material_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> DocumentChunkListResponse:
    """分页列出指定资料分块。"""
    await _ensure_kb_exists(kb_service, kb_id)
    await _ensure_material_in_kb(service, kb_id=kb_id, material_id=material_id)
    await _ensure_chunk_browsing_unlocked(ingestion_service, kb_id=kb_id)

    chunks, total = await service.list_chunks_by_material_page(
        kb_id=kb_id,
        material_id=material_id,
        skip=skip,
        limit=limit,
    )
    items = [DocumentChunkRead.model_validate(chunk) for chunk in chunks]
    return DocumentChunkListResponse(
        items=items,
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(items)) < total,
        ),
    )


@router.get(
    "/knowledge-bases/{kb_id}/materials/{material_id}/chunks/{chunk_id}",
    response_model=DocumentChunkRead,
)
async def get_material_chunk(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    ingestion_service: IngestionBatchServiceDep,
    kb_id: uuid.UUID,
    material_id: uuid.UUID,
    chunk_id: uuid.UUID,
) -> DocumentChunkRead:
    """获取指定资料下单个分块详情。"""
    await _ensure_kb_exists(kb_service, kb_id)
    await _ensure_material_in_kb(service, kb_id=kb_id, material_id=material_id)
    await _ensure_chunk_browsing_unlocked(ingestion_service, kb_id=kb_id)

    chunk = await service.get_chunk_by_id(
        kb_id=kb_id,
        material_id=material_id,
        chunk_id=chunk_id,
    )
    if chunk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHUNK_NOT_FOUND", "message": "分块不存在"},
        )

    return DocumentChunkRead.model_validate(chunk)


@router.post(
    "/knowledge-bases/{kb_id}/materials",
    response_model=SourceMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_material(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    kb_id: uuid.UUID,
    body: MaterialCreateText | MaterialCreateUrl,
) -> SourceMaterialRead:
    """创建资料（文本/URL）。"""
    await _ensure_kb_exists(kb_service, kb_id)

    if isinstance(body, MaterialCreateText):
        material = await service.create_text(
            kb_id=kb_id, title=body.title, text=body.text
        )
    else:
        material = await service.create_url(kb_id=kb_id, title=body.title, url=body.url)

    return SourceMaterialRead.model_validate(material)


@router.post(
    "/knowledge-bases/{kb_id}/materials/upload",
    response_model=SourceMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material(
    kb_service: KnowledgeBaseServiceDep,
    service: MaterialServiceDep,
    kb_id: uuid.UUID,
    title: str = Form(...),
    file: UploadFile = File(...),
) -> SourceMaterialRead:
    """上传文件资料。"""
    kb = await kb_service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    index_config = IndexConfig.model_validate(kb.index_config or {})
    if index_config.chunking.general_strategy == ChunkingStrategy.MARKDOWN_HEADING:
        filename = (file.filename or "").strip()
        if not filename.lower().endswith(".md"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "KB_MARKDOWN_ONLY",
                    "message": "当前知识库仅支持上传 .md 文件",
                },
            )

    material = await service.upload_file(
        kb_id=kb_id,
        title=title,
        file=file.file,
        filename=file.filename or "unknown",
        content_type=file.content_type,
    )

    return SourceMaterialRead.model_validate(material)
