"""知识库管理接口（CRUD + 归档）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError

from app.api.deps import AsyncSessionDep
from app.schemas.knowledge_bases import (
    ChunkingStrategy,
    IndexConfig,
    KnowledgeBaseCreate,
    KnowledgeBaseIndexConfigUpdateRequest,
    KnowledgeBaseIndexConfigUpdateResponse,
    KnowledgeBaseListResponse,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)
from app.schemas.pagination import PageMeta
from app.models.source_material import SourceType
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.index_rebuild_service import IndexRebuildService
from app.services.material_service import MaterialService

router = APIRouter()


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    db: AsyncSessionDep,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
) -> KnowledgeBaseListResponse:
    """列出所有活跃知识库。"""
    service = KnowledgeBaseService(db)
    kbs, total = await service.list_active_page(skip=skip, limit=limit)
    return KnowledgeBaseListResponse(
        items=[KnowledgeBaseRead.model_validate(kb) for kb in kbs],
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(kbs)) < total,
        ),
    )


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    db: AsyncSessionDep, body: KnowledgeBaseCreate
) -> KnowledgeBaseRead:
    """创建知识库。"""
    service = KnowledgeBaseService(db)

    # 检查名称是否已存在
    existing = await service.get_by_name(body.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "KB_NAME_EXISTS", "message": "知识库名称已存在"},
        )

    index_config = (
        body.index_config.model_dump(mode="json")
        if body.index_config is not None
        else IndexConfig().model_dump(mode="json")
    )
    kb = await service.create(
        name=body.name,
        description=body.description,
        tags=body.tags,
        index_config=index_config,
    )
    return KnowledgeBaseRead.model_validate(kb)


@router.get("/{kb_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(
    db: AsyncSessionDep, kb_id: uuid.UUID
) -> KnowledgeBaseRead:
    """获取知识库详情。"""
    service = KnowledgeBaseService(db)
    kb = await service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )
    return KnowledgeBaseRead.model_validate(kb)


@router.patch("/{kb_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    db: AsyncSessionDep, kb_id: uuid.UUID, body: KnowledgeBaseUpdate
) -> KnowledgeBaseRead:
    """更新知识库。"""
    service = KnowledgeBaseService(db)
    extra = getattr(body, "model_extra", None) or {}
    if "index_config" in extra:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INDEX_CONFIG_NOT_ALLOWED",
                "message": "index_config 不允许通过该接口更新，请使用 PUT /api/v1/knowledge-bases/{kb_id}/index-config",
            },
        )
    if extra:
        errors = [
            {
                "loc": ["body", key],
                "msg": "Extra inputs are not permitted",
                "type": "extra_forbidden",
            }
            for key in extra.keys()
        ]
        raise RequestValidationError(errors)
    kb = await service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    # 检查名称是否与其他知识库冲突
    if body.name and body.name != kb.name:
        existing = await service.get_by_name(body.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "KB_NAME_EXISTS", "message": "知识库名称已存在"},
            )

    kb = await service.update(
        kb_id=kb_id,
        name=body.name,
        description=body.description,
        tags=body.tags,
    )
    return KnowledgeBaseRead.model_validate(kb)


@router.put(
    "/{kb_id}/index-config",
    response_model=KnowledgeBaseIndexConfigUpdateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_index_config(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
    body: KnowledgeBaseIndexConfigUpdateRequest,
    response: Response,
) -> KnowledgeBaseIndexConfigUpdateResponse:
    """Replace index_config and trigger rebuild."""
    kb_service = KnowledgeBaseService(db)
    kb = await kb_service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    new_config = body.index_config.model_dump(mode="json")
    if kb.index_config == new_config:
        response.status_code = status.HTTP_200_OK
        return KnowledgeBaseIndexConfigUpdateResponse(
            knowledge_base=KnowledgeBaseRead.model_validate(kb),
            rebuild_job=None,
        )

    if body.index_config.chunking.general_strategy == ChunkingStrategy.MARKDOWN_HEADING:
        # Pre-check: markdown_heading only supports Markdown uploads; block switching if existing
        # uploaded materials include non-.md files.
        material_service = MaterialService(db)
        skip = 0
        limit = 200
        while True:
            materials = await material_service.list_by_kb(kb_id, skip=skip, limit=limit)
            if not materials:
                break
            for material in materials:
                if material.source_type != SourceType.UPLOAD:
                    continue
                filename = (material.uri or "").rsplit("/", 1)[-1]
                if not filename.lower().endswith(".md"):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "KB_MARKDOWN_ONLY_CONFLICT",
                            "message": "切换为 markdown_heading 前请先清理/迁移非 .md 上传资料",
                        },
                    )
            if len(materials) < limit:
                break
            skip += limit

    rebuild_service = IndexRebuildService(db)
    job = await rebuild_service.create_job(kb=kb, index_config=new_config)
    return KnowledgeBaseIndexConfigUpdateResponse(
        knowledge_base=KnowledgeBaseRead.model_validate(kb),
        rebuild_job=job,
    )


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
    confirm: bool = Query(..., description="二次确认（true 才执行）"),
) -> None:
    """删除知识库（需二次确认）。"""
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "CONFIRM_REQUIRED", "message": "需要确认删除"},
        )

    service = KnowledgeBaseService(db)
    kb = await service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    await service.delete(kb_id)


@router.post("/{kb_id}/archive", response_model=KnowledgeBaseRead)
async def archive_knowledge_base(
    db: AsyncSessionDep, kb_id: uuid.UUID
) -> KnowledgeBaseRead:
    """归档知识库。"""
    service = KnowledgeBaseService(db)
    kb = await service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    kb = await service.archive(kb_id)
    return KnowledgeBaseRead.model_validate(kb)
