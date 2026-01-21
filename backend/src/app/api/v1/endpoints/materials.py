"""资料管理接口（列表/创建/上传）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from app.api.deps import AsyncSessionDep
from app.schemas.materials import (
    MaterialCreateText,
    MaterialCreateUrl,
    MaterialListResponse,
    SourceMaterialRead,
)
from app.schemas.pagination import PageMeta
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.material_service import MaterialService

router = APIRouter()


@router.get(
    "/knowledge-bases/{kb_id}/materials",
    response_model=MaterialListResponse,
)
async def list_materials(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> MaterialListResponse:
    """列出知识库下的所有资料。"""
    kb_service = KnowledgeBaseService(db)
    kb = await kb_service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    service = MaterialService(db)
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


@router.post(
    "/knowledge-bases/{kb_id}/materials",
    response_model=SourceMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_material(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
    body: MaterialCreateText | MaterialCreateUrl,
) -> SourceMaterialRead:
    """创建资料（文本/URL）。"""
    kb_service = KnowledgeBaseService(db)
    kb = await kb_service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    service = MaterialService(db)

    if isinstance(body, MaterialCreateText):
        material = await service.create_text(
            kb_id=kb_id, title=body.title, text=body.text
        )
    else:
        material = await service.create_url(
            kb_id=kb_id, title=body.title, url=body.url
        )

    return SourceMaterialRead.model_validate(material)


@router.post(
    "/knowledge-bases/{kb_id}/materials/upload",
    response_model=SourceMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
    title: str = Form(...),
    file: UploadFile = File(...),
) -> SourceMaterialRead:
    """上传文件资料。"""
    kb_service = KnowledgeBaseService(db)
    kb = await kb_service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    service = MaterialService(db)
    material = await service.upload_file(
        kb_id=kb_id,
        title=title,
        file=file.file,
        filename=file.filename or "unknown",
        content_type=file.content_type,
    )

    return SourceMaterialRead.model_validate(material)
