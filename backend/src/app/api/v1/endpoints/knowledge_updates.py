"""候选沉淀 API 端点。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import AsyncSessionDep, CurrentUserDep
from app.core.errors import AppError, ErrorCode
from app.models.knowledge_update_proposal import ProposalStatus
from app.schemas.knowledge_updates import ProposalCreate, ProposalRead, ProposalUpdate
from app.services.knowledge_update_service import KnowledgeUpdateService

router = APIRouter()


@router.post("", response_model=ProposalRead, status_code=201)
async def create_proposal(
    req: ProposalCreate, session: AsyncSessionDep, _user: CurrentUserDep
) -> ProposalRead:
    """创建候选沉淀。"""
    proposal = await KnowledgeUpdateService().create_proposal(session, req)
    return ProposalRead.model_validate(proposal)


@router.get("", response_model=list[ProposalRead])
async def list_proposals(
    session: AsyncSessionDep,
    _user: CurrentUserDep,
    kb_id: uuid.UUID | None = Query(None),
    status: ProposalStatus | None = Query(None),
) -> list[ProposalRead]:
    """列出候选沉淀。"""
    proposals = await KnowledgeUpdateService().list_proposals(
        session, kb_id=kb_id, status=status
    )
    return [ProposalRead.model_validate(p) for p in proposals]


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
