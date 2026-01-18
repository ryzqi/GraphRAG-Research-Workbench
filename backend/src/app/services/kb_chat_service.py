"""知识库问答服务。

使用 LangGraph 图实现，支持检查点持久化。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_chat_graph import KbChatGraph, KbChatState
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.core.checkpoint import CheckpointManager
from app.core.logging import set_run_id
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.prompts import get_prompt_loader
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
        self._prompts = get_prompt_loader()

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

    @staticmethod
    def _to_langchain_message(msg: LLMMessage) -> SystemMessage | HumanMessage | AIMessage:
        role = (msg.role or "").lower()
        if role == "system":
            return SystemMessage(content=msg.content)
        if role == "assistant":
            return AIMessage(content=msg.content)
        return HumanMessage(content=msg.content)

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
        await self._db.commit()
        set_run_id(str(run.id))

        try:
            kb_ids = session.selected_kb_ids or []
            default_kb_ids = [uuid.UUID(str(kid)) for kid in kb_ids]

            # kb_retrieve：通过回调收集检索结果（用于 Evidence 落库/指标）
            retrieval_results: list = []
            seen_chunk_ids: set[uuid.UUID] = set()
            retrieval_usage: dict[str, int] | None = None
            retrieval_truncation: dict[str, int | bool] | None = None

            def _on_results(included: list, meta: dict[str, Any]) -> None:
                nonlocal retrieval_usage, retrieval_truncation
                for r in included:
                    chunk_id = getattr(getattr(r, "chunk", None), "id", None)
                    if chunk_id and chunk_id not in seen_chunk_ids:
                        retrieval_results.append(r)
                        seen_chunk_ids.add(chunk_id)
                retrieval_usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else None
                retrieval_truncation = meta.get("truncation") if isinstance(meta.get("truncation"), dict) else None

            kb_tool = build_kb_retrieve_tool(
                retrieval=self._retrieval,
                default_kb_ids=default_kb_ids,
                context_builder=self._context_builder,
                on_results=_on_results,
            )

            tools, tool_meta_by_name = await build_tool_registry(
                settings=self._settings,
                mcp=None,
                extensions=None,
                extra_tools=[kb_tool],
                include_web_search=False,
                include_mcp=False,
            )

            chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url.rstrip("/"),
            )

            system_prompt = self._prompts.render("kb_chat/system")
            history_messages, history_usage, history_truncation = (
                self._context_builder.build_history_messages(
                    history=history,
                    summary_text=summary.content if summary else None,
                )
            )
            context_metrics = self._context_builder.build_metrics(
                history_usage=history_usage,
                history_truncation=history_truncation,
            )

            messages = [
                SystemMessage(content=system_prompt),
                *[self._to_langchain_message(m) for m in history_messages],
                HumanMessage(content=user_content),
            ]

            graph = KbChatGraph(
                chat_model=chat_model,
                tools=tools,
                tool_meta_by_name=tool_meta_by_name,
            )

            state: KbChatState = {
                "messages": messages,
                "pending_tool_calls": [],
                "stage_summaries": {},
                "metrics": {"context": context_metrics},
                "force_kb_retrieve": True,
            }
            result = await graph.run(
                state,
                thread_id=str(session.id),
                checkpointer=CheckpointManager.get_checkpointer(),
            )

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            answer = ""
            result_messages = result.get("messages")
            if isinstance(result_messages, list):
                for msg in reversed(result_messages):
                    if isinstance(msg, AIMessage):
                        answer = str(msg.content or "")
                        break

            # 补齐结构化检索结果与指标（供 Evidence 落库/观测）
            result["retrieval_results"] = retrieval_results
            metrics = result.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}
            context_metrics = self._context_builder.build_metrics(
                history_usage=history_usage,
                history_truncation=history_truncation,
                retrieval_usage=retrieval_usage,
                retrieval_truncation=retrieval_truncation,
            )
            metrics = {
                **metrics,
                "context": context_metrics,
                "retrieval_usage": retrieval_usage or {"tokens": 0, "chars": 0, "items": 0},
                "retrieval_truncation": retrieval_truncation
                or {"truncated": False, "dropped_items": 0, "dropped_tokens": 0},
            }
            result["metrics"] = metrics

            stage_summaries = result.get("stage_summaries")
            if not isinstance(stage_summaries, dict):
                stage_summaries = {}
            retrieval_stats = self._retrieval.last_stats
            stage_summaries = {
                **stage_summaries,
                "retrieval": {
                    "count": len(retrieval_results),
                    "filtered_count": getattr(retrieval_stats, "filtered_count", 0) if retrieval_stats else 0,
                    "min_score": getattr(retrieval_stats, "min_score", None) if retrieval_stats else None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            }
            result["stage_summaries"] = stage_summaries

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
        finally:
            set_run_id(None)
