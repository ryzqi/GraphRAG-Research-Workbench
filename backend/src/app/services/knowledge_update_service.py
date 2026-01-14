"""候选沉淀服务。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_update_proposal import KnowledgeUpdateProposal, ProposalStatus
from app.schemas.knowledge_updates import ProposalCreate, ProposalUpdate


class KnowledgeUpdateService:
    """候选沉淀服务。"""

    async def create_proposal(
        self, session: AsyncSession, req: ProposalCreate
    ) -> KnowledgeUpdateProposal:
        """创建候选沉淀。"""
        proposal = KnowledgeUpdateProposal(
            kb_id=req.kb_id,
            source_run_id=req.source_run_id,
            summary=req.summary,
            payload=req.payload,
            status=ProposalStatus.PENDING,
        )
        session.add(proposal)
        await session.commit()
        await session.refresh(proposal)
        return proposal

    async def list_proposals(
        self,
        session: AsyncSession,
        *,
        kb_id: uuid.UUID | None = None,
        status: ProposalStatus | None = None,
    ) -> list[KnowledgeUpdateProposal]:
        """列出候选沉淀。"""
        stmt = select(KnowledgeUpdateProposal).order_by(
            KnowledgeUpdateProposal.created_at.desc()
        )
        if kb_id:
            stmt = stmt.where(KnowledgeUpdateProposal.kb_id == kb_id)
        if status:
            stmt = stmt.where(KnowledgeUpdateProposal.status == status)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_proposals_page(
        self,
        session: AsyncSession,
        *,
        kb_id: uuid.UUID | None = None,
        status: ProposalStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[KnowledgeUpdateProposal], int]:
        """分页列出候选沉淀。"""
        conditions = []
        if kb_id:
            conditions.append(KnowledgeUpdateProposal.kb_id == kb_id)
        if status:
            conditions.append(KnowledgeUpdateProposal.status == status)

        count_stmt = select(func.count()).select_from(KnowledgeUpdateProposal)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total = int((await session.execute(count_stmt)).scalar_one())

        stmt = (
            select(KnowledgeUpdateProposal)
            .order_by(
                KnowledgeUpdateProposal.created_at.desc(),
                KnowledgeUpdateProposal.id.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        if conditions:
            stmt = stmt.where(*conditions)
        result = await session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_proposal(
        self, session: AsyncSession, proposal_id: uuid.UUID
    ) -> KnowledgeUpdateProposal | None:
        """获取候选沉淀。"""
        return await session.get(KnowledgeUpdateProposal, proposal_id)

    async def update_proposal(
        self, session: AsyncSession, proposal_id: uuid.UUID, req: ProposalUpdate
    ) -> KnowledgeUpdateProposal | None:
        """更新候选沉淀状态。"""
        proposal = await session.get(KnowledgeUpdateProposal, proposal_id)
        if not proposal:
            return None

        if req.status is not None:
            proposal.status = req.status
            if req.status in (ProposalStatus.APPROVED, ProposalStatus.REJECTED):
                proposal.reviewed_at = datetime.now(timezone.utc)
        if req.reviewed_by is not None:
            proposal.reviewed_by = req.reviewed_by

        await session.commit()
        await session.refresh(proposal)
        return proposal
