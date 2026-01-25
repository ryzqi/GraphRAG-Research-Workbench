"""知识库问答服务。

使用 LangGraph 图实现，支持检查点持久化。
"""

from __future__ import annotations

import logging
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_chat_graph import KbChatGraph, build_kb_chat_graph
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.core.checkpoint import CheckpointManager
from app.core.memory_store import StoreManager
from app.core.logging import set_run_id
from app.core.settings import get_settings
from app.integrations.langchain_profiles import build_chat_model_profile
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
from app.services.streaming import (
    LegacyThinkParser,
    StreamState,
    apply_updates_chunk,
    extract_answer_text,
    extract_stream_delta,
)
from app.agents.kb_chat_memory import append_kb_chat_memory_entry

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

    def _build_graph(
        self,
        *,
        chat_model: ChatOpenAI,
        tools: list,
        tool_meta_by_name: dict,
    ):
        """根据灰度开关选择 KB Chat 图；agentic 不可用时回退到 legacy。"""
        return build_kb_chat_graph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
        )

    def _build_trace_snapshot(self, *, layer_stats: dict[str, Any]) -> dict[str, Any]:
        """Build a minimal, non-sensitive snapshot for production observability."""
        prompt_version = None
        try:
            prompt_version = self._prompts.get("kb_chat/system").version
        except Exception:
            prompt_version = None

        return {
            "config": {
                "flow_version": self._settings.kb_chat_flow_version,
                "force_retrieve": bool(self._settings.kb_chat_force_retrieve),
                "total_timeout_seconds": float(self._settings.kb_chat_total_timeout_seconds),
                "max_total_rounds": int(self._settings.kb_chat_max_total_rounds),
                "max_retrieval_retries": int(self._settings.kb_chat_max_retrieval_retries),
                "max_generation_retries": int(self._settings.kb_chat_max_generation_retries),
                "ambiguity_check_enabled": bool(self._settings.kb_chat_ambiguity_check_enabled),
                "decomposition_enabled": bool(self._settings.kb_chat_decomposition_enabled),
                "decomposition_max_sub_questions": int(self._settings.kb_chat_decomposition_max_sub_questions),
                "multi_query_enabled": bool(self._settings.kb_chat_multi_query_enabled),
                "multi_query_max_variants": int(self._settings.kb_chat_multi_query_max_variants),
                "hyde_enabled": bool(self._settings.kb_chat_hyde_enabled),
                "hyde_max_queries": int(self._settings.kb_chat_hyde_max_queries),
            },
            "versions": {
                "llm_model": self._settings.llm_model,
                "embedding_model": self._settings.embedding_model,
                "rerank_model": self._settings.retrieval_rerank_model,
                "kb_chat_system_prompt": prompt_version,
            },
            "retrieval_layer_stats": layer_stats,
        }

    @staticmethod
    def _build_retrieval_stage_summary(
        *,
        retrieval_results: list,
        retrieval_stats: object | None,
        layer_stats: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "count": len(retrieval_results),
            "filtered_count": getattr(retrieval_stats, "filtered_count", 0) if retrieval_stats else 0,
            "min_score": getattr(retrieval_stats, "min_score", None) if retrieval_stats else None,
            "dense_hits": layer_stats.get("dense_hits"),
            "bm25_hits": layer_stats.get("bm25_hits"),
            "rrf_candidates": layer_stats.get("rrf_candidates"),
            "rerank_applied": layer_stats.get("rerank_applied"),
            "rerank_reason": layer_stats.get("rerank_reason"),
            "rerank_latency_ms": layer_stats.get("rerank_latency_ms"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

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
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages")

        use_checkpoint_messages = (
            checkpoint_tuple is not None
            and isinstance(existing_messages, list)
            and bool(existing_messages)
        )

        summary = None
        history: list[LLMMessage] = []
        if not use_checkpoint_messages:
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
            evidence_draft_items: list[dict[str, Any]] = []
            seen_evidence_chunk_ids: set[str] = set()
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

                items = meta.get("evidence_items")
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        cid = it.get("chunk_id")
                        if isinstance(cid, str) and cid and cid not in seen_evidence_chunk_ids:
                            evidence_draft_items.append(it)
                            seen_evidence_chunk_ids.add(cid)

            kb_tool = build_kb_retrieve_tool(
                retrieval=self._retrieval,
                default_kb_ids=default_kb_ids,
                context_builder=self._context_builder,
                on_results=_on_results,
            )

            tools, tool_meta_by_name = await build_tool_registry(
                settings=self._settings,
                extensions=None,
                extra_tools=[kb_tool],
                include_web_search=False,
                include_mcp=False,
            )

            chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url.rstrip("/"),
                profile=build_chat_model_profile(self._settings),
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

            messages: list[SystemMessage | HumanMessage | AIMessage] = []
            if not use_checkpoint_messages:
                messages.append(SystemMessage(content=system_prompt))
            messages.extend([self._to_langchain_message(m) for m in history_messages])
            messages.append(HumanMessage(content=user_content))

            graph = self._build_graph(
                chat_model=chat_model,
                tools=tools,
                tool_meta_by_name=tool_meta_by_name,
            )
            if isinstance(graph, KbChatGraph):
                state: dict = {
                    "messages": messages,
                    "pending_tool_calls": [],
                    "stage_summaries": {},
                    "metrics": {"context": context_metrics},
                    "force_kb_retrieve": self._settings.kb_chat_force_retrieve,
                }
            else:
                from app.agents.kb_chat_agentic_state import make_initial_state

                state = make_initial_state(
                    user_input=user_content,
                    messages=messages,
                    memory_keys={
                        "user_id": "local",
                        "thread_id": str(session.id),
                        "kb_ids": [str(kid) for kid in (session.selected_kb_ids or [])],
                    },
                )
                state["metrics"] = {"context": context_metrics}
                state["force_kb_retrieve"] = self._settings.kb_chat_force_retrieve

            store = None
            try:
                store = StoreManager.get_store()
            except Exception:
                store = None
            result = await graph.run(
                state,
                thread_id=thread_id,
                checkpointer=CheckpointManager.get_checkpointer(),
                store=store,
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
            result["evidence_items"] = evidence_draft_items
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
            layer_draft = self._retrieval.last_layer_draft
            layer_stats = (
                dict(layer_draft.stats)
                if layer_draft is not None and isinstance(getattr(layer_draft, "stats", None), dict)
                else {}
            )
            stage_summaries = {
                **stage_summaries,
                "retrieval": self._build_retrieval_stage_summary(
                    retrieval_results=retrieval_results,
                    retrieval_stats=retrieval_stats,
                    layer_stats=layer_stats,
                ),
            }
            result["stage_summaries"] = stage_summaries

            if self._settings.kb_chat_trace_enabled:
                metrics = {
                    **metrics,
                    **self._build_trace_snapshot(layer_stats=layer_stats),
                }
                result["metrics"] = metrics

            return await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                answer=answer,
                retrieval_results=retrieval_results,
                stage_summaries=stage_summaries,
                metrics=metrics,
            )

        except asyncio.CancelledError:
            run.status = AgentRunStatus.CANCELED
            run.finished_at = datetime.now(timezone.utc)
            await asyncio.shield(self._db.commit())
            raise
        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()
            raise
        finally:
            set_run_id(None)

    async def answer_stream(
        self,
        *,
        session: ChatSession,
        user_content: str,
        request: object | None = None,
    ) -> Any:
        """处理用户问题并生成答案（流式 SSE）。"""
        started_at = datetime.now(timezone.utc)
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get("channel_values", {})
            existing_messages = checkpoint_values.get("messages")

        use_checkpoint_messages = (
            checkpoint_tuple is not None
            and isinstance(existing_messages, list)
            and bool(existing_messages)
        )

        summary = None
        history: list[LLMMessage] = []
        if not use_checkpoint_messages:
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
            evidence_draft_items: list[dict[str, Any]] = []
            seen_evidence_chunk_ids: set[str] = set()
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

                items = meta.get("evidence_items")
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        cid = it.get("chunk_id")
                        if isinstance(cid, str) and cid and cid not in seen_evidence_chunk_ids:
                            evidence_draft_items.append(it)
                            seen_evidence_chunk_ids.add(cid)
            kb_tool = build_kb_retrieve_tool(
                retrieval=self._retrieval,
                default_kb_ids=default_kb_ids,
                context_builder=self._context_builder,
                on_results=_on_results,
            )

            tools, tool_meta_by_name = await build_tool_registry(
                settings=self._settings,
                extensions=None,
                extra_tools=[kb_tool],
                include_web_search=False,
                include_mcp=False,
            )

            chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.llm_api_key,
                base_url=self._settings.llm_base_url.rstrip("/"),
                profile=build_chat_model_profile(self._settings),
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
            messages: list[SystemMessage | HumanMessage | AIMessage] = []
            if not use_checkpoint_messages:
                messages.append(SystemMessage(content=system_prompt))
            messages.extend([self._to_langchain_message(m) for m in history_messages])
            messages.append(HumanMessage(content=user_content))

            graph = self._build_graph(
                chat_model=chat_model,
                tools=tools,
                tool_meta_by_name=tool_meta_by_name,
            )
            if isinstance(graph, KbChatGraph):
                state: dict = {
                    "messages": messages,
                    "pending_tool_calls": [],
                    "stage_summaries": {},
                    "metrics": {"context": context_metrics},
                    "force_kb_retrieve": self._settings.kb_chat_force_retrieve,
                }
            else:
                from app.agents.kb_chat_agentic_state import make_initial_state

                state = make_initial_state(
                    user_input=user_content,
                    messages=messages,
                    memory_keys={
                        "user_id": "local",
                        "thread_id": thread_id,
                        "kb_ids": [str(kid) for kid in (session.selected_kb_ids or [])],
                    },
                )
                state["metrics"] = {"context": context_metrics}
                state["force_kb_retrieve"] = self._settings.kb_chat_force_retrieve
            yield "meta", {
                "run_id": str(run.id),
                "session_id": str(session.id),
                "session_type": session.session_type.value,
                "thread_id": thread_id,
                "mode": session.mode.value,
            }

            stream_state = StreamState(
                messages=list(state.get("messages") or []),
                pending_tool_calls=list(state.get("pending_tool_calls") or []),
                stage_summaries=dict(state.get("stage_summaries") or {}),
                metrics=dict(state.get("metrics") or {}),
            )
            legacy_think_parser = LegacyThinkParser()

            store = None
            try:
                store = StoreManager.get_store()
            except Exception:
                store = None
            compiled = graph.compile(
                checkpointer=CheckpointManager.get_checkpointer(),
                store=store,
            )
            config = CheckpointManager.make_config(thread_id)
            stream = compiled.astream(
                state,
                config,
                stream_mode=["messages", "updates"],
            )
            async for mode, chunk in stream:
                if request is not None:
                    is_disconnected = getattr(request, "is_disconnected", None)
                    if callable(is_disconnected) and await is_disconnected():
                        try:
                            await stream.aclose()
                        except Exception:
                            pass
                        run.status = AgentRunStatus.CANCELED
                        run.finished_at = datetime.now(timezone.utc)
                        await self._db.commit()
                        return

                if mode == "messages":
                    token, _meta = chunk
                    deltas = extract_stream_delta(
                        token,
                        _meta if isinstance(_meta, dict) else None,
                        legacy_think_parser=legacy_think_parser,
                    )
                    for delta in deltas:
                        yield "delta", delta.to_dict()
                    continue

                if mode == "updates" and isinstance(chunk, dict):
                    apply_updates_chunk(stream_state, chunk)
            for delta in legacy_think_parser.flush():
                yield "delta", delta.to_dict()
            answer = ""
            for msg in reversed(stream_state.messages):
                if isinstance(msg, AIMessage):
                    answer = extract_answer_text(msg.content)
                    break

            metrics = stream_state.metrics
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
            stage_summaries = stream_state.stage_summaries
            if not isinstance(stage_summaries, dict):
                stage_summaries = {}
            retrieval_stats = self._retrieval.last_stats
            layer_draft = self._retrieval.last_layer_draft
            layer_stats = (
                dict(layer_draft.stats)
                if layer_draft is not None and isinstance(getattr(layer_draft, "stats", None), dict)
                else {}
            )
            stage_summaries = {
                **stage_summaries,
                "retrieval": self._build_retrieval_stage_summary(
                    retrieval_results=retrieval_results,
                    retrieval_stats=retrieval_stats,
                    layer_stats=layer_stats,
                ),
            }

            if self._settings.kb_chat_trace_enabled:
                metrics = {
                    **metrics,
                    **self._build_trace_snapshot(layer_stats=layer_stats),
                }

            final_response = await self._finalize_run(
                session=session,
                run=run,
                started_at=started_at,
                answer=answer,
                retrieval_results=retrieval_results,
                evidence_draft_items=evidence_draft_items,
                stage_summaries=stage_summaries,
                metrics=metrics,
            )
            yield "final", final_response.model_dump(mode="json")

        except asyncio.CancelledError:
            run.status = AgentRunStatus.CANCELED
            run.finished_at = datetime.now(timezone.utc)
            await asyncio.shield(self._db.commit())
            raise
        except Exception as e:
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await self._db.commit()
            yield "error", {
                "code": "CHAT_STREAM_FAILED",
                "message": str(e),
            }
        finally:
            set_run_id(None)

    async def _finalize_run(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        started_at: datetime,
        answer: str,
        retrieval_results: list,
        evidence_draft_items: list[dict[str, Any]] | None = None,
        stage_summaries: dict[str, Any],
        metrics: dict[str, Any],
    ) -> ChatAnswerResponse:
        # answer 已经剥离思考段（<think>/thinking/reasoning_content）

        # 保存证据（先构建，再对答案做引用约束，避免落库/返回不一致）
        def _parse_uuid(value: object) -> uuid.UUID | None:
            if value is None:
                return None
            try:
                return uuid.UUID(str(value))
            except Exception:
                return None

        evidence_items: list[EvidenceItem] = []
        seen_evidence_chunk_ids: set[uuid.UUID] = set()

        if evidence_draft_items:
            for it in evidence_draft_items:
                if not isinstance(it, dict):
                    continue

                chunk_id = _parse_uuid(it.get("chunk_id"))
                if chunk_id and chunk_id in seen_evidence_chunk_ids:
                    continue

                source_kind_raw = it.get("source_kind")
                source_kind = (
                    EvidenceSourceKind.KB
                    if source_kind_raw == "kb"
                    else EvidenceSourceKind.EXTERNAL
                )

                kb_id = _parse_uuid(it.get("kb_id"))
                material_id = _parse_uuid(it.get("material_id"))
                if source_kind == EvidenceSourceKind.KB and (chunk_id is None or kb_id is None or material_id is None):
                    # KB evidence must be chunk-traceable.
                    continue

                excerpt = str(it.get("excerpt") or "")[:500]
                if not excerpt.strip():
                    continue

                locator = it.get("locator") if isinstance(it.get("locator"), dict) else None

                self._db.add(
                    Evidence(
                        run_id=run.id,
                        source_kind=source_kind,
                        kb_id=kb_id,
                        material_id=material_id,
                        chunk_id=chunk_id,
                        locator=locator,
                        excerpt=excerpt,
                    )
                )
                evidence_items.append(
                    EvidenceItem(
                        source_kind=source_kind.value,
                        kb_id=kb_id,
                        material_id=material_id,
                        chunk_id=chunk_id,
                        locator=locator,
                        excerpt=excerpt,
                    )
                )
                if chunk_id:
                    seen_evidence_chunk_ids.add(chunk_id)
        else:
            for r in retrieval_results:
                ev = Evidence(
                    run_id=run.id,
                    source_kind=EvidenceSourceKind.KB,
                    kb_id=r.chunk.kb_id,
                    material_id=r.chunk.material_id,
                    chunk_id=r.chunk.id,
                    locator=r.chunk.locator,
                    excerpt=r.chunk.content[:500],
                )
                self._db.add(ev)
                evidence_items.append(
                    EvidenceItem(
                        source_kind=EvidenceSourceKind.KB.value,
                        kb_id=r.chunk.kb_id,
                        material_id=r.chunk.material_id,
                        chunk_id=r.chunk.id,
                        locator=r.chunk.locator,
                        excerpt=r.chunk.content[:500],
                    )
                )

        # 强约束：引用必须与证据数量一致；无证据（非澄清）时禁止输出看似引用的编号/ID。
        force_exit = stage_summaries.get("force_exit") if isinstance(stage_summaries, dict) else None
        allow_no_evidence = isinstance(force_exit, dict) and force_exit.get("reason") == "clarify"
        from app.services.evidence_guardrails import enforce_kb_answer_citation_guardrails

        answer = enforce_kb_answer_citation_guardrails(
            answer,
            evidence_count=len(evidence_items),
            allow_no_evidence=allow_no_evidence,
        )

        # Best-effort: write a small, structured memory entry (bounded + TTL).
        if self._settings.memory_enabled:
            try:
                await append_kb_chat_memory_entry(
                    store=StoreManager.get_store(),
                    user_id="local",
                    thread_id=str(session.id),
                    kb_ids=[str(k) for k in (session.selected_kb_ids or [])],
                    question=str(run.question or "").strip(),
                    answer=extract_answer_text(answer),
                    run_id=str(run.id),
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("写入 KB Chat 记忆失败: %s", exc)

        # 保存助手消息
        assistant_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content=answer,
        )
        self._db.add(assistant_msg)
        summary_metrics: dict[str, object] = {}
        try:
            summary_result = await self._summary_service.maybe_update_summary(session.id)
            if summary_result:
                summary_metrics = {
                    "summary_updated": True,
                    **summary_result.stats,
                }
        except Exception as exc:  # pragma: no cover
            logger.warning("摘要更新失败: %s", exc)

        # 更新运行状态
        run.status = AgentRunStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        run.final_output = answer
        run.stage_summaries = stage_summaries
        run.metrics = {
            "evidence_count": len(evidence_items),
            "evidence_chunk_ids": [
                str(item.chunk_id) for item in evidence_items if item.chunk_id is not None
            ],
            "latency_ms": int((run.finished_at - started_at).total_seconds() * 1000),
            **summary_metrics,
            **metrics,
        }

        await self._db.commit()
        await self._db.refresh(assistant_msg)
        await self._db.refresh(run)

        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=evidence_items,
            run=AgentRunRead.model_validate(run),
        )
