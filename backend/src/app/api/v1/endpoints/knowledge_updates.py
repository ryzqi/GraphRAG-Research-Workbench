"""候选沉淀 API 端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.models.knowledge_update_proposal import ProposalStatus
from app.schemas.knowledge_updates import (
    ProposalCreate,
    ProposalListResponse,
    ProposalRead,
    ProposalUpdate,
)
from app.schemas.pagination import PageMeta
from app.services.knowledge_update_service import KnowledgeUpdateService

router = APIRouter()


@router.post("", response_model=ProposalRead, status_code=201)
async def create_proposal(
    req: ProposalCreate, session: AsyncSessionDep, _user: CurrentUserDep
) -> ProposalRead:
    """创建候选沉淀。"""
    proposal = await KnowledgeUpdateService().create_proposal(session, req)
    return ProposalRead.model_validate(proposal)


@router.get("", response_model=ProposalListResponse)
async def list_proposals(
    session: AsyncSessionDep,
    _user: CurrentUserDep,
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
    kb_id: uuid.UUID | None = Query(None),
    status: ProposalStatus | None = Query(None),
) -> ProposalListResponse:
    """列出候选沉淀。"""
    proposals, total = await KnowledgeUpdateService().list_proposals_page(
        session,
        kb_id=kb_id,
        status=status,
        skip=skip,
        limit=limit,
    )
    return ProposalListResponse(
        items=[ProposalRead.model_validate(p) for p in proposals],
        page=PageMeta(
            skip=skip,
            limit=limit,
            total=total,
            has_more=(skip + len(proposals)) < total,
        ),
    )


@router.get("/{proposal_id}", response_model=ProposalRead)
async def get_proposal(
    proposal_id: uuid.UUID, session: AsyncSessionDep, _user: CurrentUserDep
) -> ProposalRead:
    """获取候选沉淀详情。"""
    proposal = await KnowledgeUpdateService().get_proposal(session, proposal_id)
    if proposal is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="候选沉淀不存在",
            status_code=404,
        )
    return ProposalRead.model_validate(proposal)


@router.patch("/{proposal_id}", response_model=ProposalRead)
async def update_proposal(
    proposal_id: uuid.UUID, req: ProposalUpdate, session: AsyncSessionDep, _user: CurrentUserDep
) -> ProposalRead:
    """更新候选沉淀状态。"""
    proposal = await KnowledgeUpdateService().update_proposal(session, proposal_id, req)
    if proposal is None:
        raise AppError(
            code=ErrorCode.NOT_FOUND.value,
            message="候选沉淀不存在",
            status_code=404,
        )
    return ProposalRead.model_validate(proposal)
