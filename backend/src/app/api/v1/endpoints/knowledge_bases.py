"""知识库管理接口（CRUD + 归档）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AsyncSessionDep
from app.schemas.knowledge_bases import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
)
from app.schemas.pagination import PageMeta
from app.services.knowledge_base_service import KnowledgeBaseService

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

    kb = await service.create(
        name=body.name,
        description=body.description,
        tags=body.tags,
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
