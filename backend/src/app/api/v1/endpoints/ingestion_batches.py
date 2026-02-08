"""Unified ingestion-batch APIs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import AsyncSessionDep
from app.schemas.ingestion_batches import (
    IngestionBatchCancelResponse,
    IngestionBatchCreateRequest,
    IngestionBatchRead,
    IngestionBatchRetryResponse,
    IngestionBatchSubmitResponse,
)
from app.services.ingestion_batch_service import IngestionBatchService

router = APIRouter()


@router.post("", response_model=IngestionBatchSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_ingestion_batch(
    db: AsyncSessionDep,
    body: IngestionBatchCreateRequest,
    request: Request,
) -> IngestionBatchSubmitResponse:
    service = IngestionBatchService(db)
    requested_by = request.headers.get("X-User")
    return await service.submit_manifest(
        kb_id=body.kb_id,
        entries=body.entries,
        requested_by=requested_by,
    )


@router.get("/{batch_id}", response_model=IngestionBatchRead)
async def get_ingestion_batch(
    db: AsyncSessionDep,
    batch_id: uuid.UUID,
) -> IngestionBatchRead:
    service = IngestionBatchService(db)
    return await service.get_batch(batch_id=batch_id)


@router.post("/{batch_id}/retry", response_model=IngestionBatchRetryResponse)
async def retry_ingestion_batch(
    db: AsyncSessionDep,
    batch_id: uuid.UUID,
) -> IngestionBatchRetryResponse:
    service = IngestionBatchService(db)
    return await service.retry_failed_docs(batch_id=batch_id)


@router.post("/{batch_id}/cancel", response_model=IngestionBatchCancelResponse)
async def cancel_ingestion_batch(
    db: AsyncSessionDep,
    batch_id: uuid.UUID,
) -> IngestionBatchCancelResponse:
    service = IngestionBatchService(db)
    return await service.cancel_batch(batch_id=batch_id)
