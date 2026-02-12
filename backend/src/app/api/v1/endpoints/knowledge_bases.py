"""知识库管理接口（CRUD + 归档）。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from app.api.deps import AsyncSessionDep
from app.models.knowledge_base import (
    KnowledgeBaseReadiness as ModelKnowledgeBaseReadiness,
    KnowledgeBaseStatus as ModelKnowledgeBaseStatus,
)
from app.models.source_material import SourceType
from app.schemas.ingestion_batches import KnowledgeBaseIngestionStateRead
from app.schemas.knowledge_bases import (
    ChunkingStrategy,
    KnowledgeBaseCreate,
    KnowledgeBaseIndexConfigUpdateRequest,
    KnowledgeBaseIndexConfigUpdateResponse,
    KnowledgeBaseListResponse,
    KnowledgeBaseRead,
    KnowledgeBaseReadinessFilter,
    KnowledgeBaseStatusFilter,
    KnowledgeBaseUpdate,
)
from app.schemas.pagination import PageMeta
from app.services.index_rebuild_service import IndexRebuildService
from app.services.ingestion_batch_service import IngestionBatchService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.material_service import MaterialService

router = APIRouter()


def _is_kb_name_conflict_error(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == "23505":
        return True

    message = str(orig or exc).lower()
    return "knowledge_bases_name_key" in message or (
        "duplicate" in message and "knowledge_bases" in message and "name" in message
    )


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    db: AsyncSessionDep,
    skip: Annotated[int, Query(ge=0, description="跳过记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="返回记录数")] = 100,
    status: Annotated[KnowledgeBaseStatusFilter, Query(description="按状态过滤")] = KnowledgeBaseStatusFilter.ACTIVE,
    readiness: Annotated[KnowledgeBaseReadinessFilter, Query(description="按 readiness 过滤")] = KnowledgeBaseReadinessFilter.ALL,
) -> KnowledgeBaseListResponse:
    """列出知识库（默认 active；可按 readiness 二次过滤）。"""

    service = KnowledgeBaseService(db)
    model_status = (
        None
        if status == KnowledgeBaseStatusFilter.ALL
        else ModelKnowledgeBaseStatus(status.value)
    )
    model_readiness = (
        None
        if readiness == KnowledgeBaseReadinessFilter.ALL
        else ModelKnowledgeBaseReadiness(readiness.value)
    )

    kbs, total = await service.list_page(
        skip=skip,
        limit=limit,
        status=model_status,
        readiness=model_readiness,
    )
    return KnowledgeBaseListResponse(
        items=[KnowledgeBaseRead.model_validate(kb) for kb in kbs],
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(kbs)) < total,
        ),
    )


@router.get("/selectable", response_model=KnowledgeBaseListResponse)
async def list_selectable_knowledge_bases(
    db: AsyncSessionDep,
    skip: Annotated[int, Query(ge=0, description="跳过记录数")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="返回记录数")] = 100,
) -> KnowledgeBaseListResponse:
    """业务入口口径：仅返回 status=active 且 readiness=ready 的知识库。"""

    service = KnowledgeBaseService(db)
    kbs, total = await service.list_selectable_page(skip=skip, limit=limit)
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
    db: AsyncSessionDep,
    body: KnowledgeBaseCreate,
) -> KnowledgeBaseRead:
    service = KnowledgeBaseService(db)

    existing = await service.get_by_name(body.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "KB_NAME_EXISTS", "message": "知识库名称已存在"},
        )

    if body.index_config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INDEX_CONFIG_REQUIRED",
                "message": "创建知识库时必须提供 index_config，并显式配置多尺度窗口参数",
            },
        )

    index_config = body.index_config.model_dump(mode="json")
    try:
        kb = await service.create(
            name=body.name,
            description=body.description,
            tags=body.tags,
            index_config=index_config,
        )
    except IntegrityError as exc:
        await db.rollback()
        if _is_kb_name_conflict_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "KB_NAME_EXISTS", "message": "知识库名称已存在"},
            ) from exc
        raise

    return KnowledgeBaseRead.model_validate(kb)


@router.get("/{kb_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(db: AsyncSessionDep, kb_id: uuid.UUID) -> KnowledgeBaseRead:
    service = KnowledgeBaseService(db)
    kb = await service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )
    return KnowledgeBaseRead.model_validate(kb)


@router.get("/{kb_id}/ingestion-state", response_model=KnowledgeBaseIngestionStateRead)
async def get_knowledge_base_ingestion_state(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
) -> KnowledgeBaseIngestionStateRead:
    service = IngestionBatchService(db)
    return await service.get_kb_ingestion_state(kb_id=kb_id)


@router.patch("/{kb_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    db: AsyncSessionDep,
    kb_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
) -> KnowledgeBaseRead:
    service = KnowledgeBaseService(db)
    extra = getattr(body, "model_extra", None) or {}
    if "index_config" in extra:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    await db.refresh(kb)
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
async def archive_knowledge_base(db: AsyncSessionDep, kb_id: uuid.UUID) -> KnowledgeBaseRead:
    service = KnowledgeBaseService(db)
    kb = await service.get_by_id(kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    kb = await service.archive(kb_id)
    return KnowledgeBaseRead.model_validate(kb)
