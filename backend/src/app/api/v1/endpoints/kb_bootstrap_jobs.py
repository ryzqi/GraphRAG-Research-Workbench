from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AsyncSessionDep
from app.core.errors import not_found
from app.models.kb_bootstrap_job import KBBootstrapJob
from app.schemas.kb_bootstrap_jobs import (
    BootstrapSubmissionCreateRequest,
    BootstrapSubmissionCreateResponse,
    BootstrapSubmissionFinalizeResponse,
    BootstrapSubmissionRead,
    BootstrapSubmissionStatus,
)
from app.services.kb_bootstrap_job_service import KBBootstrapJobService

router = APIRouter()


async def _to_read(
    *,
    service: KBBootstrapJobService,
    job: KBBootstrapJob,
) -> BootstrapSubmissionRead:
    upload_targets = await service.build_upload_targets(job=job)
    upload_progress = service.get_upload_progress(job)
    return BootstrapSubmissionRead(
        id=job.id,
        kb_id=job.kb_id,
        batch_id=job.batch_id,
        status=BootstrapSubmissionStatus(job.status.value),
        total_entries=job.total_entries,
        accepted_entries=job.accepted_entries,
        failed_entries=job.failed_entries,
        entry_errors=job.entry_errors or [],
        progress_message=job.progress_message,
        error_code=job.error_code,
        error_message=job.error_message,
        upload_progress=upload_progress,
        upload_targets=upload_targets,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/knowledge-bases/bootstrap-submissions",
    response_model=BootstrapSubmissionCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_bootstrap_submission(
    req: BootstrapSubmissionCreateRequest,
    session: AsyncSessionDep,
    request: Request,
) -> BootstrapSubmissionCreateResponse:
    service = KBBootstrapJobService(session)
    result = await service.create_submission(
        req=req,
        request_id=request.headers.get("X-Request-Id"),
        requested_by=request.headers.get("X-User"),
    )
    return BootstrapSubmissionCreateResponse(
        job_id=result.job.id,
        kb_id=result.job.kb_id,
        status=BootstrapSubmissionStatus(result.job.status.value),
        upload_targets=result.upload_targets,
        upload_progress=result.upload_progress,
    )


@router.post(
    "/knowledge-bases/bootstrap-submissions/{job_id}/finalize",
    response_model=BootstrapSubmissionFinalizeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def finalize_bootstrap_submission(
    job_id: uuid.UUID,
    session: AsyncSessionDep,
) -> BootstrapSubmissionFinalizeResponse:
    service = KBBootstrapJobService(session)
    job = await service.finalize_submission(job_id=job_id)
    return BootstrapSubmissionFinalizeResponse(
        job_id=job.id,
        kb_id=job.kb_id,
        status=BootstrapSubmissionStatus(job.status.value),
        upload_progress=service.get_upload_progress(job),
    )


@router.get(
    "/knowledge-bases/bootstrap-submissions/{job_id}",
    response_model=BootstrapSubmissionRead,
)
async def get_bootstrap_submission(
    job_id: uuid.UUID,
    session: AsyncSessionDep,
) -> BootstrapSubmissionRead:
    service = KBBootstrapJobService(session)
    job = await service.get_submission(job_id=job_id)
    if job is None:
        raise not_found(message="任务不存在", code="KB_BOOTSTRAP_JOB_NOT_FOUND")
    return await _to_read(service=service, job=job)

