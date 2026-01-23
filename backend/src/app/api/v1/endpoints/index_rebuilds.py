"""Index rebuild job endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AsyncSessionDep
from app.schemas.index_rebuilds import IndexRebuildJobRead
from app.services.index_rebuild_service import IndexRebuildService

router = APIRouter()


@router.get("/{job_id}", response_model=IndexRebuildJobRead)
async def get_index_rebuild_job(
    db: AsyncSessionDep, job_id: uuid.UUID
) -> IndexRebuildJobRead:
    """Get index rebuild job status."""
    service = IndexRebuildService(db)
    job = await service.get_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "Index rebuild job not found"},
        )
    return IndexRebuildJobRead.model_validate(job)
