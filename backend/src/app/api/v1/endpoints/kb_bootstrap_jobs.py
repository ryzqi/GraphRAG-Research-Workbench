from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import AsyncSessionDep
from app.core.errors import not_found
from app.models.kb_bootstrap_job import KBBootstrapJob
from app.schemas.kb_bootstrap_jobs import (
    BootstrapCreateKnowledgeBaseRequest,
    BootstrapCreateKnowledgeBaseResponse,
    BootstrapSubmissionCreateRequest,
    BootstrapSubmissionCreateResponse,
    BootstrapSubmissionFinalizeResponse,
    BootstrapSubmissionRead,
    BootstrapSubmissionStatus,
    BootstrapUploadSessionResponse,
)
from app.services.kb_bootstrap_job_service import KBBootstrapJobService
from app.services.knowledge_base_service import KnowledgeBaseService

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


def _to_read(
    *,
    service: KBBootstrapJobService,
    job: KBBootstrapJob,
) -> BootstrapSubmissionRead:
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
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/knowledge-bases/bootstrap-create",
    response_model=BootstrapCreateKnowledgeBaseResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def bootstrap_create_knowledge_base(
    req: BootstrapCreateKnowledgeBaseRequest,
    session: AsyncSessionDep,
    request: Request,
) -> BootstrapCreateKnowledgeBaseResponse:
    kb_service = KnowledgeBaseService(session)
    existing = await kb_service.get_by_name(req.kb.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "KB_NAME_EXISTS", "message": "知识库名称已存在"},
        )

    if req.kb.index_config is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INDEX_CONFIG_REQUIRED",
                "message": "创建知识库时必须提供 index_config，并显式配置多尺度窗口参数",
            },
        )

    bootstrap_service = KBBootstrapJobService(session)
    try:
        kb = await kb_service.create(
            name=req.kb.name,
            description=req.kb.description,
            tags=req.kb.tags,
            index_config=req.kb.index_config.model_dump(mode="json"),
            commit=False,
        )
        result = await bootstrap_service.create_submission(
            req=BootstrapSubmissionCreateRequest(kb_id=kb.id, entries=req.entries),
            request_id=None,
            requested_by=request.headers.get("X-User"),
        )
    except IntegrityError as exc:
        await session.rollback()
        if _is_kb_name_conflict_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "KB_NAME_EXISTS", "message": "知识库名称已存在"},
            ) from exc
        raise

    return BootstrapCreateKnowledgeBaseResponse(
        kb_id=result.job.kb_id,
        job_id=result.job.id,
        status=BootstrapSubmissionStatus(result.job.status.value),
        monitor_url=f"/api/v1/knowledge-bases/bootstrap-submissions/{result.job.id}",
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


@router.post(
    "/knowledge-bases/bootstrap-submissions/{job_id}/upload-session",
    response_model=BootstrapUploadSessionResponse,
)
async def create_bootstrap_upload_session(
    job_id: uuid.UUID,
    session: AsyncSessionDep,
) -> BootstrapUploadSessionResponse:
    service = KBBootstrapJobService(session)
    result = await service.create_upload_session(job_id=job_id)
    return BootstrapUploadSessionResponse(
        job_id=result.job.id,
        kb_id=result.job.kb_id,
        status=BootstrapSubmissionStatus(result.job.status.value),
        upload_targets=result.upload_targets,
        upload_progress=result.upload_progress,
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
    return _to_read(service=service, job=job)
