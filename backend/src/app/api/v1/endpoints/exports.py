from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import AsyncSessionDep
from app.core.errors import AppError, ErrorCode
from app.schemas.exports import ExportCreateRequest, ExportJob
from app.services.export_service import ExportService

router = APIRouter()


@router.post("", response_model=ExportJob, status_code=202)
async def create_export(
    req: ExportCreateRequest, session: AsyncSessionDep
) -> ExportJob:
    job = await ExportService().create_export(session, req)
    return ExportJob.model_validate(job)


@router.get("/{export_id}", response_model=ExportJob)
async def get_export(export_id: uuid.UUID, session: AsyncSessionDep) -> ExportJob:
    job = await ExportService().get_export(session, export_id)
    if job is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="导出任务不存在",
            status_code=404,
        )
    return ExportJob.model_validate(job)
