"""统一 ingestion-batch 接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import AsyncSessionDep
from app.api.sse import SSE_HEADERS, encode_sse
from app.schemas.ingestion_batches import (
    IngestionBatchCancelResponse,
    IngestionBatchCreateRequest,
    IngestionBatchRead,
    IngestionBatchRetryResponse,
    IngestionBatchSubmitResponse,
)
from app.services.ingestion_batch_service import IngestionBatchService

router = APIRouter()


@router.post(
    "",
    response_model=IngestionBatchSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
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


@router.get(
    "/latest",
    response_model=IngestionBatchRead,
    responses={status.HTTP_204_NO_CONTENT: {"description": "No ingestion batch found"}},
)
async def get_latest_ingestion_batch(
    db: AsyncSessionDep,
    kb_id: uuid.UUID = Query(..., description="知识库 ID"),
    prefer_active: bool = Query(True, description="优先返回运行中的批次"),
) -> IngestionBatchRead | Response:
    service = IngestionBatchService(db)
    batch = await service.get_latest_batch_for_kb(
        kb_id=kb_id,
        prefer_active=prefer_active,
    )
    if batch is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return batch


@router.get("/{batch_id}", response_model=IngestionBatchRead)
async def get_ingestion_batch(
    db: AsyncSessionDep,
    batch_id: uuid.UUID,
) -> IngestionBatchRead:
    service = IngestionBatchService(db)
    return await service.get_batch(batch_id=batch_id)


@router.get("/{batch_id}/stream")
async def stream_ingestion_batch(
    db: AsyncSessionDep,
    batch_id: uuid.UUID,
    request: Request,
):
    service = IngestionBatchService(db)
    await service.get_batch(batch_id=batch_id)

    async def _events():
        yield "meta", {"batch_id": str(batch_id), "type": "ingestion_batch"}
        async for event, payload in service.stream_batch_updates(batch_id=batch_id):
            if await request.is_disconnected():
                return
            yield event, payload

    return StreamingResponse(
        encode_sse(_events()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


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
