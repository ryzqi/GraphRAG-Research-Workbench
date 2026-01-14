"""知识库问答服务。

使用 LangGraph 图实现，支持检查点持久化。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_chat_graph import KbChatGraph, KbChatState
from app.core.checkpoint import CheckpointManager
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.rerank_client import RerankClient
from app.integrations.redis_client import get_redis
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence, EvidenceSourceKind
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    EvidenceItem,
)
from app.services.context_builder import ContextBuilder
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)


class KbChatService:
    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
        milvus: MilvusClient,
        embedding: EmbeddingClient,
        reranker: RerankClient | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._settings = get_settings()
        redis = get_redis()
        self._retrieval = RetrievalService(db, milvus, embedding, redis, reranker=reranker)
        self._context_builder = ContextBuilder(self._settings)
        self._summary_service = ConversationSummaryService(db, settings=self._settings)

    async def _load_history(
        self, session_id: uuid.UUID, limit: int
    ) -> list[LLMMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit * 2)
        )
        result = await self._db.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()
        filtered = [m for m in messages if not self._summary_service.is_summary_message(m)]
        if len(filtered) > limit:
            filtered = filtered[-limit:]
        return [
            LLMMessage(role=msg.role.value, content=msg.content)
            for msg in filtered
        ]

    async def answer(
        self,
        *,
        session: ChatSession,
        user_content: str,
    ) -> ChatAnswerResponse:
        """处理用户问题并生成答案（使用 LangGraph）。"""
        started_at = datetime.now(timezone.utc)
        summary = await self._summary_service.load_latest_summary(session.id)
        history = await self._load_history(
            session.id, limit=self._settings.context_history_max_messages
        )

        # 保存用户消息
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=user_content,
        )
        self._db.add(user_msg)

        # 创建运行记录
        run = AgentRun(
            run_type=AgentRunType.KB_ANSWER,
            session_id=session.id,
            question=user_content,
            selected_kb_ids=session.selected_kb_ids,
            allow_external=session.allow_external,
            mode=session.mode,
            status=AgentRunStatus.RUNNING,
            started_at=started_at,
        )
        self._db.add(run)
        await self._db.flush()

        try:
            # 创建 LangGraph 图
            graph = KbChatGraph(
                llm=self._llm,
                retrieval=self._retrieval,
                context_builder=self._context_builder,
            )

            # 使用 session_id 作为 thread_id 执行
            kb_ids = session.selected_kb_ids or []
            state = KbChatState(
                question=user_content,
                kb_ids=[uuid.UUID(str(kid)) for kid in kb_ids],
                history=history,
                summary=summary.content if summary else None,
            )
            result = await graph.run(
                state,
                thread_id=str(session.id),
                checkpointer=CheckpointManager.get_checkpointer(),
            )

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            answer = str(result.get("answer") or "")
            retrieval_results = result.get("retrieval_results") or []
            if not isinstance(retrieval_results, list):
                retrieval_results = []

            # 保存助手消息
            assistant_msg = ChatMessage(
                session_id=session.id,
                role=MessageRole.ASSISTANT,
                content=answer,
            )
            self._db.add(assistant_msg)

            summary_metrics: dict[str, object] = {}
            try:
                summary_result = await self._summary_service.maybe_update_summary(
                    session.id
                )
                if summary_result:
                    summary_metrics = {
                        "summary_updated": True,
                        "summary_message_id": str(summary_result.message.id),
                        **summary_result.stats,
                    }
            except Exception as exc:  # pragma: no cover
                logger.warning("摘要更新失败: %s", exc)

            # 保存证据
            evidence_items: list[EvidenceItem] = []
            for r in retrieval_results:
                ev = Evidence(
                    run_id=run.id,
                    source_kind=EvidenceSourceKind.KB,
                    kb_id=r.chunk.kb_id,
                    material_id=r.chunk.material_id,
                    chunk_id=r.chunk.id,
                    locator=r.chunk.locator,
                    excerpt=r.chunk.text[:500],
                )
                self._db.add(ev)
                evidence_items.append(
                    EvidenceItem(
                        source_kind=EvidenceSourceKind.KB,
                        kb_id=r.chunk.kb_id,
                        material_id=r.chunk.material_id,
                        chunk_id=r.chunk.id,
                        locator=r.chunk.locator,
                        excerpt=r.chunk.text[:500],
                    )
                )

            # 更新运行状态
            run.status = AgentRunStatus.SUCCEEDED
            run.finished_at = datetime.now(timezone.utc)
            run.final_output = answer
            run.stage_summaries = result.get("stage_summaries")
            run.metrics = {
                "evidence_count": len(evidence_items),
                "latency_ms": int(
                    (run.finished_at - started_at).total_seconds() * 1000
                ),
                **summary_metrics,
                **(result.get("metrics") or {}),
            }

            await self._db.commit()
            await self._db.refresh(assistant_msg)
            await self._db.refresh(run)

            return ChatAnswerResponse(
                assistant_message=ChatMessageRead.model_validate(assistant_msg),
                evidence=evidence_items,
                run=AgentRunRead.model_validate(run),
            )

        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()
            raise
