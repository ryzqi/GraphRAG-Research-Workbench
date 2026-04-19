from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.dependencies.app_resources import AppResourcesDep
from app.api.dependencies.services import ExportServiceDep
from app.api.deps import AsyncSessionDep
from app.core.errors import AppError, ErrorCode
from app.core.settings import get_settings
from app.integrations.object_storage import ObjectRef
from app.models.export_job import ExportStatus as ExportJobStatus
from app.schemas.exports import ExportCreateRequest, ExportJob

router = APIRouter()


def _build_export_download_response(
    *,
    export_id: uuid.UUID,
    run_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> tuple[str, str, dict[str, str]]:
    if session_id is not None and run_id is None:
        return (
            f"exports/research/{export_id}.pdf",
            "application/pdf",
            {
                "Content-Disposition": (
                    f'attachment; filename="research-report-{session_id}.pdf"'
                )
            },
        )

    if run_id is not None and session_id is None:
        return (
            f"exports/chat/{export_id}.md",
            "text/markdown; charset=utf-8",
            {"Content-Disposition": f'attachment; filename="{export_id}.md"'},
        )

    if run_id is not None and session_id is not None:
        raise AppError(
            code="EXPORT_TARGET_AMBIGUOUS",
            message="导出任务目标标识冲突",
            status_code=400,
        )

    raise AppError(
        code="EXPORT_TARGET_MISSING",
        message="导出任务缺少目标标识",
        status_code=400,
    )


@router.post("", response_model=ExportJob, status_code=202)
async def create_export(
    req: ExportCreateRequest,
    session: AsyncSessionDep,
    service: ExportServiceDep,
) -> ExportJob:
    job = await service.create_export(session, req)
    return ExportJob.model_validate(job)


@router.get("/{export_id}", response_model=ExportJob)
async def get_export(
    export_id: uuid.UUID,
    session: AsyncSessionDep,
    service: ExportServiceDep,
) -> ExportJob:
    job = await service.get_export(session, export_id)
    if job is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="导出任务不存在",
            status_code=404,
        )
    return ExportJob.model_validate(job)


@router.get("/{export_id}/download")
async def download_export(
    export_id: uuid.UUID,
    session: AsyncSessionDep,
    service: ExportServiceDep,
    resources: AppResourcesDep,
) -> StreamingResponse:
    job = await service.get_export(session, export_id)
    if job is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="导出任务不存在",
            status_code=404,
        )
    if job.status == ExportJobStatus.FAILED:
        raise AppError(
            code=job.error_code or "EXPORT_FAILED",
            message=job.error_message or "导出任务失败",
            status_code=409,
        )
    if job.status != ExportJobStatus.SUCCEEDED:
        raise AppError(
            code="EXPORT_NOT_READY",
            message="导出任务尚未完成",
            status_code=409,
        )

    object_name, media_type, headers = _build_export_download_response(
        export_id=job.id,
        run_id=job.run_id,
        session_id=job.session_id,
    )
    storage = resources.object_storage
    await storage.ensure_buckets()
    ref = ObjectRef(
        bucket=get_settings().minio_bucket_exports,
        object_name=object_name,
    )
    if not await storage.exists(ref):
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="导出文件不存在",
            status_code=404,
        )
    return StreamingResponse(
        storage.iter_bytes(ref),
        media_type=media_type,
        headers=headers,
    )
