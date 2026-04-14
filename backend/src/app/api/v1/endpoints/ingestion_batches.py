"""统一 ingestion-batch 接口。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.app_resources import AppResourcesDep
from app.api.dependencies.services import (
    IngestionBatchServiceDep,
    open_ingestion_batch_service_scope,
)
from app.api.sse import SSE_HEADERS, encode_sse
from app.bootstrap.app_resources import AppResources
from app.schemas.ingestion_batches import (
    IngestionBatchCancelResponse,
    IngestionBatchCreateRequest,
    IngestionBatchRead,
    IngestionBatchRetryResponse,
    IngestionBatchSubmitResponse,
)

router = APIRouter()


async def _stream_ingestion_batch_events(
    *,
    resources: AppResources,
    batch_id: uuid.UUID,
    request: Request,
):
    async with open_ingestion_batch_service_scope(resources=resources) as (
        _db,
        service,
    ):
        yield "meta", {"batch_id": str(batch_id), "type": "ingestion_batch"}
        async for event, payload in service.stream_batch_updates(batch_id=batch_id):
            if await request.is_disconnected():
                return
            yield event, payload


@router.post(
    "",
    response_model=IngestionBatchSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ingestion_batch(
    service: IngestionBatchServiceDep,
    body: IngestionBatchCreateRequest,
    request: Request,
) -> IngestionBatchSubmitResponse:
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
    service: IngestionBatchServiceDep,
    kb_id: uuid.UUID = Query(..., description="知识库 ID"),
    prefer_active: bool = Query(True, description="优先返回运行中的批次"),
) -> IngestionBatchRead | Response:
    batch = await service.get_latest_batch_for_kb(
        kb_id=kb_id,
        prefer_active=prefer_active,
    )
    if batch is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return batch


@router.get("/{batch_id}", response_model=IngestionBatchRead)
async def get_ingestion_batch(
    service: IngestionBatchServiceDep,
    batch_id: uuid.UUID,
) -> IngestionBatchRead:
    return await service.get_batch(batch_id=batch_id)


@router.get("/{batch_id}/stream")
async def stream_ingestion_batch(
    service: IngestionBatchServiceDep,
    resources: AppResourcesDep,
    batch_id: uuid.UUID,
    request: Request,
):
    await service.get_batch(batch_id=batch_id)

    return StreamingResponse(
        encode_sse(
            _stream_ingestion_batch_events(
                resources=resources,
                batch_id=batch_id,
                request=request,
            )
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/{batch_id}/retry", response_model=IngestionBatchRetryResponse)
async def retry_ingestion_batch(
    service: IngestionBatchServiceDep,
    batch_id: uuid.UUID,
) -> IngestionBatchRetryResponse:
    return await service.retry_failed_docs(batch_id=batch_id)


@router.post("/{batch_id}/cancel", response_model=IngestionBatchCancelResponse)
async def cancel_ingestion_batch(
    service: IngestionBatchServiceDep,
    batch_id: uuid.UUID,
) -> IngestionBatchCancelResponse:
    return await service.cancel_batch(batch_id=batch_id)
