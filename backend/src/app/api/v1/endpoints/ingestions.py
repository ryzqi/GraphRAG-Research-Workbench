"""导入任务接口（创建/查询/取消）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.schemas.ingestions import (
    IngestionJobCreateRequest,
    IngestionJobRead,
)
from app.services.ingestion_service import IngestionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.material_service import MaterialService

router = APIRouter()


@router.post(
    "",
    response_model=IngestionJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ingestion_job(
    db: AsyncSessionDep, _user: CurrentUserDep, body: IngestionJobCreateRequest
) -> IngestionJobRead:
    """创建导入任务（异步）。"""
    # 验证知识库存在
    kb_service = KnowledgeBaseService(db)
    kb = await kb_service.get_by_id(body.kb_id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "KB_NOT_FOUND", "message": "知识库不存在"},
        )

    # 验证资料存在且属于该知识库
    material_service = MaterialService(db)
    materials = await material_service.get_by_ids(body.material_ids)
    if len(materials) != len(body.material_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "MATERIAL_NOT_FOUND", "message": "部分资料不存在"},
        )

    for m in materials:
        if m.kb_id != body.kb_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MATERIAL_KB_MISMATCH",
                    "message": f"资料 {m.id} 不属于该知识库",
                },
            )

    service = IngestionService(db)
    job = await service.create_job(
        kb_id=body.kb_id,
        material_ids=body.material_ids,
        mode=body.mode,
    )

    return IngestionJobRead.model_validate(job)


@router.get("/{ingestion_id}", response_model=IngestionJobRead)
async def get_ingestion_job(
    db: AsyncSessionDep, _user: CurrentUserDep, ingestion_id: uuid.UUID
) -> IngestionJobRead:
    """获取导入任务状态。"""
    service = IngestionService(db)
    job = await service.get_by_id(ingestion_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "导入任务不存在"},
        )

    return IngestionJobRead.model_validate(job)


@router.post("/{ingestion_id}/cancel", response_model=IngestionJobRead)
async def cancel_ingestion_job(
    db: AsyncSessionDep, _user: CurrentUserDep, ingestion_id: uuid.UUID
) -> IngestionJobRead:
    """取消导入任务。"""
    service = IngestionService(db)
    job = await service.cancel(ingestion_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "导入任务不存在"},
        )

    return IngestionJobRead.model_validate(job)
