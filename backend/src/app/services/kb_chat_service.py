"""知识库问答服务。

使用 LangGraph 图实现，支持检查点持久化。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_chat_agentic.json_safety import ensure_json_safe
from app.agents.kb_chat_graph import build_kb_chat_graph
from app.agents.kb_chat_memory import append_kb_chat_memory_entry
from app.agents.tool_calling.registry import build_tool_registry
from app.agents.tools.kb_retrieve import build_kb_retrieve_tool
from app.core.checkpoint import CheckpointManager
from app.core.errors import AppError, bad_request
from app.core.logging import set_run_id
from app.core.memory_store import StoreManager
from app.core.settings import get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.integrations.chat_model_factory import create_chat_model, get_active_model_identity
from app.integrations.llm_client import ChatMessage as LLMMessage
from app.integrations.llm_client import LLMClient
from app.integrations.milvus_client import MilvusClient
from app.integrations.redis_client import RedisClient
from app.integrations.rerank_client import RerankClient
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.models.chat_message import ChatMessage, MessageRole
from app.models.chat_session import ChatSession
from app.models.evidence import Evidence, EvidenceSourceKind
from app.models.source_material import SourceMaterial
from app.prompts import get_prompt_loader
from app.schemas.chats import (
    AgentRunRead,
    ChatAnswerResponse,
    ChatMessageRead,
    KbChatConfig,
    ChatPendingUserClarificationResponse,
    EvidenceItem,
    PendingClarification,
    resolve_kb_chat_config,
)
from app.services.context_builder import ContextBuilder
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.evidence_guardrails import (
    enforce_kb_answer_citation_guardrails,
    extract_citation_labels,
    is_stable_citation_id,
    normalize_citation_label,
)
from app.services.retrieval_service import RetrievalService
from app.services.streaming import (
    StreamState,
    apply_updates_chunk,
    extract_answer_text,
    extract_stream_delta,
)

logger = logging.getLogger(__name__)
_STREAM_EVENT_VERSION = "2.0"


@dataclass
class _KbChatExecution:
    started_at: datetime
    thread_id: str
    run: AgentRun
    kb_chat_config: KbChatConfig
    history_usage: dict[str, Any]
    history_truncation: dict[str, Any]
    retrieval_results: list
    evidence_draft_items_by_round: dict[int, list[dict[str, Any]]]
    retrieval_meta: dict[str, Any]
    graph: object
    state: dict[str, Any]


class KbChatService:
    def __init__(
        self,
        db: AsyncSession,
        llm: LLMClient,
        milvus: MilvusClient,
        embedding: EmbeddingClient,
        reranker: RerankClient | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._settings = get_settings()
        self._retrieval = RetrievalService(
            db, milvus, embedding, redis, reranker=reranker
        )
        self._context_builder = ContextBuilder(self._settings)
        self._summary_service = ConversationSummaryService(db, settings=self._settings)
        self._prompts = get_prompt_loader()

    def _build_graph(
        self,
        *,
        chat_model: Any,
        tools: list,
        tool_meta_by_name: dict,
        kb_chat_config: KbChatConfig,
    ):
        """构建 KB Chat 图（agentic RAG 流程，已移除 legacy 实现）。"""
        return build_kb_chat_graph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            kb_chat_config=kb_chat_config.model_dump(mode="json"),
        )

    def _resolve_session_kb_chat_config(self, session: ChatSession) -> KbChatConfig:
        raw = session.kb_chat_config if isinstance(session.kb_chat_config, dict) else None
        return resolve_kb_chat_config(raw=raw, settings=self._settings)

    @staticmethod
    def _to_retrieval_overrides(config: KbChatConfig) -> dict[str, Any]:
        return {
            "query_rewrite_enabled": bool(config.query_rewrite_enabled),
            "hybrid_retrieval_enabled": bool(config.hybrid_retrieval_enabled),
            "rerank_enabled": bool(config.rerank_enabled),
            "retrieval_top_k": int(config.retrieval_top_k),
            "retrieval_rerank_top_k": int(config.retrieval_rerank_top_k),
            "hybrid_ranker": str(config.retrieval_hybrid_ranker),
            "hybrid_dense_weight": float(config.retrieval_hybrid_dense_weight),
            "hybrid_sparse_weight": float(config.retrieval_hybrid_sparse_weight),
            "hybrid_rrf_k": int(config.retrieval_hybrid_rrf_k),
            "parent_max_parents": int(config.retrieval_parent_max_parents),
            "parent_max_children_per_parent": int(
                config.retrieval_parent_max_children_per_parent
            ),
            "multiscale_per_window_top_k": int(
                config.retrieval_multiscale_per_window_top_k
            ),
            "multiscale_rrf_k": int(config.retrieval_multiscale_rrf_k),
            "multiscale_max_documents": int(config.retrieval_multiscale_max_documents),
            "multiscale_max_chunks_per_document": int(
                config.retrieval_multiscale_max_chunks_per_document
            ),
        }

    @staticmethod
    def _build_graph_schema_payload(
        graph_json: dict[str, Any], config: KbChatConfig
    ) -> dict[str, Any]:
        del config  # graph schema strictly reflects LangGraph topology + node metadata
        raw_nodes = graph_json.get("nodes") if isinstance(graph_json, dict) else None
        raw_edges = graph_json.get("edges") if isinstance(graph_json, dict) else None

        def _node_order(node: dict[str, Any]) -> int:
            order = node.get("order")
            if isinstance(order, int):
                return order
            return 10_000

        nodes: list[dict[str, Any]] = []
        if isinstance(raw_nodes, list):
            for raw_node in raw_nodes:
                if not isinstance(raw_node, dict):
                    continue
                node_id = raw_node.get("id")
                if not isinstance(node_id, str):
                    continue
                if node_id in {"__start__", "__end__"}:
                    continue
                metadata = (
                    raw_node.get("metadata")
                    if isinstance(raw_node.get("metadata"), dict)
                    else {}
                )
                label = metadata.get("label")
                phase = metadata.get("phase")
                order = metadata.get("order")
                nodes.append(
                    {
                        "id": node_id,
                        "label": label if isinstance(label, str) and label.strip() else node_id,
                        "phase": phase if isinstance(phase, str) else None,
                        "order": order if isinstance(order, int) else None,
                    }
                )

        nodes.sort(key=_node_order)

        edges: list[dict[str, Any]] = []
        if isinstance(raw_edges, list):
            for raw_edge in raw_edges:
                if not isinstance(raw_edge, dict):
                    continue
                source = raw_edge.get("source")
                target = raw_edge.get("target")
                if not isinstance(source, str) or not isinstance(target, str):
                    continue
                if source in {"__start__", "__end__"} or target in {"__start__", "__end__"}:
                    continue
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "conditional": bool(raw_edge.get("conditional", False)),
                    }
                )

        node_order_index = {
            node["id"]: idx for idx, node in enumerate(nodes) if isinstance(node.get("id"), str)
        }
        edges.sort(
            key=lambda edge: (
                node_order_index.get(edge["source"], 10_000),
                node_order_index.get(edge["target"], 10_000),
            )
        )

        return {"version": "1.0", "nodes": nodes, "edges": edges}

    async def get_graph_schema(
        self,
        *,
        kb_chat_config: KbChatConfig | None = None,
        selected_kb_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        config = resolve_kb_chat_config(raw=kb_chat_config, settings=self._settings)
        default_kb_ids = selected_kb_ids or []
        retrieval_overrides = self._to_retrieval_overrides(config)

        kb_tool = build_kb_retrieve_tool(
            retrieval=self._retrieval,
            default_kb_ids=default_kb_ids,
            retrieval_overrides=retrieval_overrides,
            context_builder=self._context_builder,
            on_results=lambda _included, _meta: None,
        )
        tools, tool_meta_by_name = await build_tool_registry(
            settings=self._settings,
            extensions=None,
            extra_tools=[kb_tool],
            include_web_search=False,
            include_mcp=False,
        )
        chat_model = create_chat_model(settings=self._settings)
        graph = self._build_graph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            kb_chat_config=config,
        )
        drawable_graph = graph.compile().get_graph().to_json()
        return self._build_graph_schema_payload(drawable_graph, config)

    def _build_trace_snapshot(
        self,
        *,
        layer_stats: dict[str, Any],
        kb_chat_config: KbChatConfig,
    ) -> dict[str, Any]:
        """Build a minimal, non-sensitive snapshot for production observability."""
        prompt_version = None
        try:
            prompt_version = self._prompts.get("kb_chat/system").version
        except Exception:
            prompt_version = None
        llm_model_identity = None
        try:
            provider, model = get_active_model_identity(settings=self._settings)
            llm_model_identity = f"{provider}/{model}"
        except Exception:
            llm_model_identity = None

        return {
            "config": {
                "graph_recursion_limit": int(
                    self._settings.kb_chat_graph_recursion_limit
                ),
                "max_total_rounds": int(self._settings.kb_chat_max_total_rounds),
                "max_retrieval_retries": int(
                    self._settings.kb_chat_max_retrieval_retries
                ),
                "max_generation_retries": int(
                    self._settings.kb_chat_max_generation_retries
                ),
                "query_rewrite_enabled": bool(kb_chat_config.query_rewrite_enabled),
                "ambiguity_check_enabled": bool(kb_chat_config.ambiguity_check_enabled),
                "normalize_llm_enabled": bool(kb_chat_config.normalize_llm_enabled),
                "normalize_alias_max": int(kb_chat_config.normalize_alias_max),
                "normalize_timeout_seconds": float(
                    kb_chat_config.normalize_timeout_seconds
                ),
                "hyde_enabled": bool(kb_chat_config.hyde_enabled),
                "hybrid_retrieval_enabled": bool(
                    kb_chat_config.hybrid_retrieval_enabled
                ),
                "rerank_enabled": bool(kb_chat_config.rerank_enabled),
                "retrieval_top_k": int(kb_chat_config.retrieval_top_k),
                "retrieval_rerank_top_k": int(kb_chat_config.retrieval_rerank_top_k),
                "retrieval_hybrid_ranker": str(kb_chat_config.retrieval_hybrid_ranker),
                "retrieval_hybrid_dense_weight": float(
                    kb_chat_config.retrieval_hybrid_dense_weight
                ),
                "retrieval_hybrid_sparse_weight": float(
                    kb_chat_config.retrieval_hybrid_sparse_weight
                ),
                "retrieval_hybrid_rrf_k": int(kb_chat_config.retrieval_hybrid_rrf_k),
                "retrieval_parent_max_parents": int(
                    kb_chat_config.retrieval_parent_max_parents
                ),
                "retrieval_parent_max_children_per_parent": int(
                    kb_chat_config.retrieval_parent_max_children_per_parent
                ),
                "retrieval_multiscale_per_window_top_k": int(
                    kb_chat_config.retrieval_multiscale_per_window_top_k
                ),
                "retrieval_multiscale_rrf_k": int(
                    kb_chat_config.retrieval_multiscale_rrf_k
                ),
                "retrieval_multiscale_max_documents": int(
                    kb_chat_config.retrieval_multiscale_max_documents
                ),
                "retrieval_multiscale_max_chunks_per_document": int(
                    kb_chat_config.retrieval_multiscale_max_chunks_per_document
                ),
            },
            "versions": {
                "llm_model": llm_model_identity,
                "embedding_model": self._settings.embedding_model,
                "rerank_model": self._settings.retrieval_rerank_model,
                "kb_chat_system_prompt": prompt_version,
            },
            "retrieval_layer_stats": layer_stats,
        }

    @staticmethod
    def _ensure_no_pending_tool_approval(
        *,
        pending_tool_calls: object | None,
        interrupts: object | None,
    ) -> None:
        pending = pending_tool_calls if isinstance(pending_tool_calls, list) else []
        interrupt_list = interrupts if isinstance(interrupts, list) else []
        if pending or interrupt_list:
            raise bad_request(
                code="KB_CHAT_TOOL_APPROVAL_UNSUPPORTED",
                message="KB Chat 不支持工具审批流程",
                details={
                    "pending_tool_calls": len(pending),
                    "interrupts": len(interrupt_list),
                },
            )

    @staticmethod
    def _build_retrieval_stage_summary(
        *,
        retrieval_results: list,
        retrieval_stats: object | None,
        layer_stats: dict[str, Any],
    ) -> dict[str, Any]:
        reason = None
        if retrieval_stats is not None:
            reason = getattr(retrieval_stats, "reason", None)
        if reason is None:
            reason = layer_stats.get("reason")

        summary = {
            "count": len(retrieval_results),
            "filtered_count": getattr(retrieval_stats, "filtered_count", 0)
            if retrieval_stats
            else 0,
            "min_score": getattr(retrieval_stats, "min_score", None)
            if retrieval_stats
            else None,
            "dense_hits": layer_stats.get("dense_hits"),
            "bm25_hits": layer_stats.get("bm25_hits"),
            "hyde_requested_count": layer_stats.get("hyde_requested_count"),
            "hyde_used_count": layer_stats.get("hyde_used_count"),
            "hyde_aggregation": layer_stats.get("hyde_aggregation"),
            "hyde_embedding_fallback": layer_stats.get("hyde_embedding_fallback"),
            "hyde_retry_regenerated": layer_stats.get("hyde_retry_regenerated"),
            "rrf_candidates": layer_stats.get("rrf_candidates"),
            "rerank_applied": layer_stats.get("rerank_applied"),
            "rerank_reason": layer_stats.get("rerank_reason"),
            "rerank_latency_ms": layer_stats.get("rerank_latency_ms"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            summary["reason"] = reason
        return summary

    async def _prepare_kb_chat_execution(
        self,
        *,
        session: ChatSession,
        user_content: str,
        run: AgentRun | None = None,
    ) -> _KbChatExecution:
        started_at = run.started_at if run and run.started_at else datetime.now(timezone.utc)
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        existing_messages = None
        if checkpoint_tuple is not None:
            checkpoint_values = (checkpoint_tuple.checkpoint or {}).get(
                "channel_values", {}
            )
            existing_messages = checkpoint_values.get("messages")

        use_checkpoint_messages = (
            checkpoint_tuple is not None
            and isinstance(existing_messages, list)
            and bool(existing_messages)
        )

        summary = None
        history: list[LLMMessage] = []
        history_usage: dict[str, Any] = {}
        history_truncation: dict[str, Any] = {}
        if not use_checkpoint_messages:
            summary = await self._summary_service.load_latest_summary(session.id)
            history = await self._load_history(
                session.id, limit=self._settings.context_history_max_messages
            )

            history_messages, history_usage, history_truncation = (
                self._context_builder.build_history_messages(
                    history=history,
                    summary_text=summary.content if summary else None,
                )
            )
        else:
            history_messages = []

        # 保存用户消息
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=user_content,
        )
        self._db.add(user_msg)

        # 创建或复用运行记录
        if run is None:
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
        else:
            if run.started_at is None:
                run.started_at = started_at
            run.status = AgentRunStatus.RUNNING
            run.finished_at = None
            run.error_message = None
            run.final_output = None

        await self._db.flush()
        await self._db.commit()
        set_run_id(str(run.id))

        kb_ids = session.selected_kb_ids or []
        default_kb_ids = [uuid.UUID(str(kid)) for kid in kb_ids]
        kb_chat_config = self._resolve_session_kb_chat_config(session)
        retrieval_overrides = self._to_retrieval_overrides(kb_chat_config)

        # kb_retrieve：通过回调收集检索结果（用于 Evidence 落库/指标）
        retrieval_results: list = []
        seen_chunk_ids: set[uuid.UUID] = set()
        evidence_draft_items_by_round: dict[int, list[dict[str, Any]]] = {}
        retrieval_meta: dict[str, Any] = {
            "usage": None,
            "truncation": None,
            "kb_scope": None,
            "retrieval_round": None,
        }

        def _on_results(included: list, meta: dict[str, Any]) -> None:
            for r in included:
                chunk_id = getattr(getattr(r, "chunk", None), "id", None)
                if chunk_id and chunk_id not in seen_chunk_ids:
                    retrieval_results.append(r)
                    seen_chunk_ids.add(chunk_id)
            retrieval_meta["usage"] = (
                meta.get("usage") if isinstance(meta.get("usage"), dict) else None
            )
            retrieval_meta["truncation"] = (
                meta.get("truncation")
                if isinstance(meta.get("truncation"), dict)
                else None
            )
            kb_scope = meta.get("kb_scope")
            if isinstance(kb_scope, dict):
                retrieval_meta["kb_scope"] = kb_scope

            raw_round = meta.get("retrieval_round")
            retrieval_round = self._safe_non_negative_int(raw_round)
            if retrieval_round is None:
                retrieval_round = 0
            retrieval_meta["retrieval_round"] = retrieval_round

            items = meta.get("evidence_items")
            if isinstance(items, list):
                round_items: list[dict[str, Any]] = []
                seen_evidence_chunk_ids: set[str] = set()
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    cid = it.get("chunk_id")
                    if (
                        isinstance(cid, str)
                        and cid
                        and cid not in seen_evidence_chunk_ids
                    ):
                        round_items.append(it)
                        seen_evidence_chunk_ids.add(cid)
                evidence_draft_items_by_round[retrieval_round] = round_items

        kb_tool = build_kb_retrieve_tool(
            retrieval=self._retrieval,
            default_kb_ids=default_kb_ids,
            retrieval_overrides=retrieval_overrides,
            context_builder=self._context_builder,
            on_results=_on_results,
        )

        include_mcp = False  # KB Chat invariant: no MCP/tool-approval flow.
        tools, tool_meta_by_name = await build_tool_registry(
            settings=self._settings,
            extensions=None,
            extra_tools=[kb_tool],
            include_web_search=False,
            include_mcp=include_mcp,
        )

        chat_model = create_chat_model(settings=self._settings)

        system_prompt = self._prompts.render_with_few_shot("kb_chat/system")
        context_metrics = self._context_builder.build_metrics(
            history_usage=history_usage,
            history_truncation=history_truncation,
        )

        messages: list[SystemMessage | HumanMessage | AIMessage] = []
        if not use_checkpoint_messages:
            messages.append(SystemMessage(content=system_prompt))
        if history_messages:
            messages.extend([self._to_langchain_message(m) for m in history_messages])
        messages.append(HumanMessage(content=user_content))

        graph = self._build_graph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            kb_chat_config=kb_chat_config,
        )
        from app.agents.kb_chat_agentic_state import make_initial_state

        state = make_initial_state(
            user_input=user_content,
            messages=messages,
            memory_keys={
                "user_id": "local",
                "thread_id": str(session.id),
                "kb_ids": [str(kid) for kid in (session.selected_kb_ids or [])],
            },
            runtime_config=kb_chat_config.model_dump(mode="json"),
        )
        state["metrics"] = {"context": context_metrics}

        return _KbChatExecution(
            started_at=started_at,
            thread_id=thread_id,
            run=run,
            kb_chat_config=kb_chat_config,
            history_usage=history_usage,
            history_truncation=history_truncation,
            retrieval_results=retrieval_results,
            evidence_draft_items_by_round=evidence_draft_items_by_round,
            retrieval_meta=retrieval_meta,
            graph=graph,
            state=state,
        )

    def _build_observability(
        self,
        *,
        kb_chat_config: KbChatConfig,
        history_usage: dict[str, Any],
        history_truncation: dict[str, Any],
        retrieval_meta: dict[str, Any],
        retrieval_results: list,
        base_metrics: dict[str, Any] | None,
        base_stage_summaries: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        metrics = base_metrics if isinstance(base_metrics, dict) else {}
        context_metrics = self._context_builder.build_metrics(
            history_usage=history_usage,
            history_truncation=history_truncation,
            retrieval_usage=retrieval_meta.get("usage"),
            retrieval_truncation=retrieval_meta.get("truncation"),
        )
        metrics = {
            **metrics,
            "context": context_metrics,
            "retrieval_usage": retrieval_meta.get("usage")
            or {"tokens": 0, "chars": 0, "items": 0},
            "retrieval_truncation": retrieval_meta.get("truncation")
            or {"truncated": False, "dropped_items": 0, "dropped_tokens": 0},
        }

        stage_summaries = (
            base_stage_summaries if isinstance(base_stage_summaries, dict) else {}
        )
        retrieval_stats = self._retrieval.last_stats
        layer_draft = self._retrieval.last_layer_draft
        layer_stats = (
            dict(layer_draft.stats)
            if layer_draft is not None
            and isinstance(getattr(layer_draft, "stats", None), dict)
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

        kb_scope = retrieval_meta.get("kb_scope")
        if isinstance(kb_scope, dict):
            metrics = {**metrics, "kb_scope": kb_scope}
            stage_summaries = {**stage_summaries, "kb_scope": kb_scope}

        if self._settings.kb_chat_trace_enabled:
            metrics = {
                **metrics,
                **self._build_trace_snapshot(
                    layer_stats=layer_stats,
                    kb_chat_config=kb_chat_config,
                ),
            }

        metrics = ensure_json_safe(metrics, settings=self._settings, label="metrics")
        stage_summaries = ensure_json_safe(
            stage_summaries, settings=self._settings, label="stage_summaries"
        )
        return metrics, stage_summaries

    @staticmethod
    def _apply_guardrail_metrics(
        *,
        metrics: dict[str, Any],
        stage_summaries: dict[str, Any],
        kb_scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guardrails = (
            metrics.get("guardrails") if isinstance(metrics.get("guardrails"), dict) else {}
        )
        if isinstance(kb_scope, dict):
            guardrails["kb_scope"] = kb_scope

        service_guardrail = stage_summaries.get("service_guardrail")
        if isinstance(service_guardrail, dict):
            guardrails["service_guardrail"] = service_guardrail
            reason = service_guardrail.get("reason")
            if isinstance(reason, str):
                guardrails["service_guardrail_reason"] = reason

        force_exit = stage_summaries.get("force_exit")
        if isinstance(force_exit, dict):
            guardrails["force_exit"] = force_exit
            reason = force_exit.get("reason")
            if isinstance(reason, str):
                guardrails["force_exit_reason"] = reason

        if guardrails:
            return {**metrics, "guardrails": guardrails}
        return metrics

    async def _persist_guardrail_run(
        self,
        *,
        exec_ctx: _KbChatExecution,
        run: AgentRun,
        status: AgentRunStatus,
        reason: str,
        stream_state: StreamState | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        base_metrics = (
            stream_state.metrics
            if stream_state is not None
            else (exec_ctx.state.get("metrics") if isinstance(exec_ctx.state, dict) else {})
        )
        base_stage_summaries = (
            stream_state.stage_summaries
            if stream_state is not None
            else (
                exec_ctx.state.get("stage_summaries")
                if isinstance(exec_ctx.state, dict)
                else {}
            )
        )
        metrics, stage_summaries = self._build_observability(
            kb_chat_config=exec_ctx.kb_chat_config,
            history_usage=exec_ctx.history_usage,
            history_truncation=exec_ctx.history_truncation,
            retrieval_meta=exec_ctx.retrieval_meta,
            retrieval_results=exec_ctx.retrieval_results,
            base_metrics=base_metrics if isinstance(base_metrics, dict) else {},
            base_stage_summaries=base_stage_summaries
            if isinstance(base_stage_summaries, dict)
            else {},
        )
        stage_summaries = {
            **stage_summaries,
            "service_guardrail": {
                "reason": reason,
                "completed_at": now.isoformat(),
            },
        }
        metrics = self._apply_guardrail_metrics(
            metrics=metrics,
            stage_summaries=stage_summaries,
            kb_scope=exec_ctx.retrieval_meta.get("kb_scope")
            if isinstance(exec_ctx.retrieval_meta, dict)
            else None,
        )

        run.status = status
        run.finished_at = now
        run.error_message = reason if status != AgentRunStatus.SUCCEEDED else None
        run.stage_summaries = stage_summaries
        run.metrics = {
            "latency_ms": int((now - exec_ctx.started_at).total_seconds() * 1000),
            **metrics,
        }
        await asyncio.shield(self._db.commit())

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
        filtered = [
            m for m in messages if not self._summary_service.is_summary_message(m)
        ]
        if len(filtered) > limit:
            filtered = filtered[-limit:]
        return [
            LLMMessage(role=msg.role.value, content=msg.content) for msg in filtered
        ]

    @staticmethod
    def _to_langchain_message(
        msg: LLMMessage,
    ) -> SystemMessage | HumanMessage | AIMessage:
        role = (msg.role or "").lower()
        if role == "system":
            return SystemMessage(content=msg.content)
        if role == "assistant":
            return AIMessage(content=msg.content)
        return HumanMessage(content=msg.content)

    @staticmethod
    def _default_clarification_message() -> str:
        return "为了更准确地回答，请补充对象、范围、时间或指标等关键信息。"

    @staticmethod
    def _coerce_pending_clarification(payload: Any) -> PendingClarification | None:
        if not isinstance(payload, dict):
            return None
        try:
            return PendingClarification.model_validate(payload)
        except Exception:
            return None

    @classmethod
    def _extract_clarification_pending(
        cls,
        *,
        stage_summaries: dict[str, Any],
        answer: str,
    ) -> tuple[str | None, PendingClarification | None]:
        force_exit = (
            stage_summaries.get("force_exit")
            if isinstance(stage_summaries, dict)
            else None
        )
        reason = force_exit.get("reason") if isinstance(force_exit, dict) else None
        if reason != "clarify":
            return None, None

        pending_clarification = None
        if isinstance(force_exit, dict):
            pending_clarification = cls._coerce_pending_clarification(
                force_exit.get("clarification_payload")
            )
        if pending_clarification is None:
            ambiguity_summary = (
                stage_summaries.get("ambiguity_check")
                if isinstance(stage_summaries, dict)
                else None
            )
            if isinstance(ambiguity_summary, dict):
                pending_clarification = cls._coerce_pending_clarification(
                    ambiguity_summary.get("clarification_payload")
                )

        text = extract_answer_text(answer).strip()
        if not text and pending_clarification is not None:
            text = pending_clarification.question
        if not text:
            text = cls._default_clarification_message()

        if pending_clarification is None:
            pending_clarification = PendingClarification(
                question=text,
                reason_code="mixed",
                confidence=0.0,
                model_reason=None,
                slots=[],
                suggested_answers=[],
            )

        return text, pending_clarification

    @staticmethod
    def _resolve_terminal_run_status(
        *,
        stage_summaries: dict[str, Any],
        answer: str,
    ) -> tuple[AgentRunStatus, str | None]:
        """Resolve terminal run status from guardrail summaries + final answer."""
        force_exit = (
            stage_summaries.get("force_exit")
            if isinstance(stage_summaries, dict)
            else None
        )
        if not isinstance(force_exit, dict):
            return AgentRunStatus.SUCCEEDED, None

        reason = str(force_exit.get("reason") or "").strip().lower()
        if reason == "clarify":
            return AgentRunStatus.SUCCEEDED, None

        review_passed = force_exit.get("review_passed")
        used_best_answer = force_exit.get("used_best_answer") is True
        answer_text = extract_answer_text(answer).strip()
        if (
            (review_passed is True or used_best_answer)
            and answer_text
            and "无法回答" not in answer_text
        ):
            return AgentRunStatus.SUCCEEDED, None

        message = "根据现有资料无法回答该问题（已停止重试）。"
        return AgentRunStatus.FAILED, message

    @staticmethod
    def _build_no_evidence_response(
        *,
        stage_summaries: dict[str, Any],
        selected_kb_ids: list[uuid.UUID] | None,
    ) -> str:
        reason_code = ""
        force_exit = stage_summaries.get("force_exit")
        if isinstance(force_exit, dict):
            reason_code = str(force_exit.get("reason") or "").strip().lower()

        retrieval_summary = stage_summaries.get("retrieval")
        if not reason_code and isinstance(retrieval_summary, dict):
            reason_code = str(retrieval_summary.get("reason") or "").strip().lower()

        reason_text_map = {
            "clarify": "当前问题信息不足，需要先补充关键条件",
            "max_total_rounds": "多轮检索与校验后仍无可用证据",
            "max_retrieval_retries": "多次重写检索后仍未命中相关证据",
            "max_generation_retries": "多次生成与校验后仍无法得到可引用答案",
            "fallback_closed": "评估器触发保守策略，未通过证据校验",
        }
        reason_text = reason_text_map.get(reason_code, "未检索到可用于回答的证据片段")

        stage_label_map = {
            "merge_context": "上下文合并",
            "coref_rewrite": "指代消解",
            "ambiguity_check": "歧义检测",
            "normalize_rewrite": "问题规范化",
            "decomposition": "问题拆解",
            "generate_variants": "多路查询扩展",
            "entity_expand": "实体扩展",
            "hyde": "假设文档扩展",
            "prepare_messages": "检索准备",
            "retrieval": "检索融合",
            "doc_grader": "相关性评估",
            "generator": "答案生成",
            "answer_review": "答案审查",
            "transform_query": "重写检索问题",
            "force_exit": "提前终止",
            "service_guardrail": "服务保护",
        }
        executed = [
            label
            for key, label in stage_label_map.items()
            if key in stage_summaries and isinstance(stage_summaries.get(key), dict)
        ]
        executed_text = " -> ".join(executed[:8]) if executed else "问题理解 -> 检索证据 -> 回答校验"

        kb_count = len(selected_kb_ids or [])
        suggestions = [
            "把问题改得更具体（增加实体名、时间范围、指标口径）后重试。",
            "只保留最相关的 1-2 个知识库，避免检索范围过宽。",
            "若资料尚未入库，请先补充文档再提问。",
        ]
        if reason_code == "clarify":
            suggestions[0] = "先补充缺失条件（对象、时间、范围）后继续提问。"

        return (
            "我暂时无法从当前知识库中找到足够证据来回答这个问题。\n\n"
            f"原因：{reason_text}\n"
            f"已执行流程：{executed_text}\n"
            f"当前知识库范围：{kb_count} 个。\n\n"
            "建议下一步：\n"
            f"1) {suggestions[0]}\n"
            f"2) {suggestions[1]}\n"
            f"3) {suggestions[2]}"
        )

    @staticmethod
    def _calculate_stream_progress(
        *,
        stage_status: dict[str, str],
        run_status: str,
    ) -> dict[str, int | float]:
        done_status = {"completed", "skipped"}
        observed = max(len(stage_status), 1)
        completed = sum(1 for status in stage_status.values() if status in done_status)
        terminal_status = {"succeeded", "failed", "canceled", "waiting_user"}
        if run_status in terminal_status:
            total = max(observed, completed, 1)
            completed = total
            percent = 100.0
            return {
                "completed": completed,
                "total": total,
                "percent": percent,
            }
        total = observed
        percent = round((completed / total) * 100, 1) if total else 0.0
        return {
            "completed": completed,
            "total": total,
            "percent": percent,
        }

    @staticmethod
    def _shorten_stream_text(value: object, limit: int = 120) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    @staticmethod
    def _build_node_io_summary(
        *,
        node: str,
        update: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(update, dict):
            return None

        stage_summaries = update.get("stage_summaries")
        node_summary = None
        if isinstance(stage_summaries, dict):
            summary_key = {
                "retrieve": "retrieval_layer",
                "generate": "generator",
            }.get(node, node)
            candidate = stage_summaries.get(summary_key)
            if isinstance(candidate, dict):
                node_summary = candidate

        io_summary: dict[str, Any] = {}
        if isinstance(node_summary, dict):
            for key in (
                "rewritten",
                "reason",
                "normalization_source",
                "count",
                "query_items_count",
                "hyde_docs_count",
                "requested_count",
                "generated_count",
                "hyde_regenerated",
                "hyde_reason",
                "ambiguous",
                "enabled",
                "evidence_count",
                "passed",
                "fallback_reason",
                "skipped",
                "used_best_answer",
                "review_passed",
                "latency_ms",
                "summary_source",
                "compression_ratio",
                "llm_resolve_used",
                "llm_resolve_reason",
                "fallback_used",
                "triggered",
                "confidence",
                "candidate_count",
                "selected_mention",
                "resolution_source",
                "needs_clarification_hint",
                "alias_count",
                "constraint_preserved",
                "drift_risk",
                "recall_risk",
            ):
                value = node_summary.get(key)
                if value is not None:
                    io_summary[key] = value

        if node in {"coref_rewrite", "normalize_rewrite", "transform_query"}:
            query = update.get("normalized_query") or update.get("coref_query")
            if isinstance(query, str) and query.strip():
                io_summary["query"] = KbChatService._shorten_stream_text(query, 160)

        if node in {"decomposition", "generate_variants", "entity_expand"}:
            list_key = "sub_queries" if node == "decomposition" else "multi_queries"
            values = update.get(list_key)
            if isinstance(values, list):
                io_summary["query_count"] = len([v for v in values if isinstance(v, str)])

        if node == "hyde":
            hyde_docs = update.get("hyde_docs")
            if isinstance(hyde_docs, list):
                io_summary["hyde_docs_count"] = len(
                    [doc for doc in hyde_docs if isinstance(doc, str) and doc.strip()]
                )

        if node == "prepare_messages":
            query_items = update.get("query_items")
            if isinstance(query_items, list):
                io_summary["query_items_count"] = len(query_items)

        if node == "retrieve":
            metrics = update.get("metrics")
            retrieval_layer = (
                metrics.get("retrieval_layer") if isinstance(metrics, dict) else None
            )
            if isinstance(retrieval_layer, dict):
                evidence_count = retrieval_layer.get("evidence_count")
                if isinstance(evidence_count, int):
                    io_summary["evidence_count"] = evidence_count
                attempted = retrieval_layer.get("attempted")
                if isinstance(attempted, bool):
                    io_summary["attempted"] = attempted

        if node == "generate":
            draft_answer = update.get("draft_answer")
            if isinstance(draft_answer, str) and draft_answer.strip():
                io_summary["draft_preview"] = KbChatService._shorten_stream_text(
                    draft_answer, 180
                )

        if node in {"ambiguity_check", "finalize", "force_exit"}:
            final_answer = update.get("final_answer")
            if isinstance(final_answer, str) and final_answer.strip():
                io_summary["final_preview"] = KbChatService._shorten_stream_text(
                    final_answer, 180
                )

        if node == "answer_review":
            best_answer = update.get("best_answer")
            if isinstance(best_answer, str) and best_answer.strip():
                io_summary["best_answer_preview"] = KbChatService._shorten_stream_text(
                    best_answer, 120
                )

        if not io_summary:
            return None
        return io_summary

    @staticmethod
    def _build_stream_state_payload(
        *,
        run_id: uuid.UUID,
        run_status: str,
        current_step_id: str | None,
        current_node: str | None,
        stage_status: dict[str, str],
        stage_attempts: dict[str, int],
        state_version: int,
        active_path: list[str] | None = None,
        last_good_answer: str | None = None,
        degrade_reason: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        current_step_status = (
            stage_status.get(current_step_id) if current_step_id else None
        )
        current_attempt = (
            stage_attempts.get(current_step_id) if current_step_id else None
        )
        current_label = current_step_id if current_step_id else None
        return {
            "run_id": str(run_id),
            "run_status": run_status,
            "current_step_id": current_step_id,
            "current_step_label": current_label,
            "current_step_status": current_step_status,
            "current_node": current_node,
            "attempt": current_attempt,
            "message": message,
            "state_version": state_version,
            "active_path": active_path or [],
            "last_good_answer": last_good_answer,
            "degrade_reason": degrade_reason,
            "progress": KbChatService._calculate_stream_progress(
                stage_status=stage_status, run_status=run_status
            ),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _build_protocol_event_payload(
        *,
        event_type: str,
        run_id: uuid.UUID,
        payload: dict[str, Any],
        node: dict[str, str] | None = None,
        tool: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "type": event_type,
            "version": _STREAM_EVENT_VERSION,
            "run": {"id": str(run_id)},
        }
        if node:
            node_id = node.get("id")
            node_name = node.get("name")
            envelope["node"] = {
                "id": str(node_id or node_name or ""),
                "name": str(node_name or node_id or ""),
            }
        if tool:
            envelope["tool"] = tool
        return {**payload, **envelope}

    @staticmethod
    def _build_node_io_payload(
        *,
        run_id: uuid.UUID,
        node_name: str,
        node_id: str,
        phase: str,
        attempt: int | None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        input_snapshot: dict[str, Any] | None = None,
        output_snapshot: dict[str, Any] | None = None,
        error_summary: str | None = None,
        latency_ms: int | None = None,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": str(run_id),
            "node_name": node_name,
            "node_id": node_id,
            "phase": phase,
            "attempt": attempt,
            "ts": (ts or datetime.now(timezone.utc)).isoformat(),
        }
        if input_summary is not None:
            payload["input_summary"] = input_summary
        if output_summary is not None:
            payload["output_summary"] = output_summary
        if input_snapshot is not None:
            payload["input_snapshot"] = input_snapshot
        if output_snapshot is not None:
            payload["output_snapshot"] = output_snapshot
        if error_summary is not None:
            payload["error_summary"] = error_summary
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        return KbChatService._build_protocol_event_payload(
            event_type="node_io",
            run_id=run_id,
            payload=payload,
            node={"id": node_id, "name": node_name},
        )

    @staticmethod
    def _json_safe_custom_payload(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        try:
            import json

            return json.loads(json.dumps(value, default=str))
        except Exception:
            return None

    @staticmethod
    def _normalize_graph_stream_event(event: Any) -> tuple[str, Any] | None:
        """Normalize LangGraph stream tuple for both plain and subgraph modes."""
        if isinstance(event, tuple):
            if len(event) == 2:
                mode, chunk = event
            elif len(event) == 3:
                _, mode, chunk = event
            else:
                return None
            return (mode, chunk) if isinstance(mode, str) else None
        if isinstance(event, list):
            if len(event) == 2:
                mode, chunk = event[0], event[1]
            elif len(event) == 3:
                mode, chunk = event[1], event[2]
            else:
                return None
            return (mode, chunk) if isinstance(mode, str) else None
        return None

    @staticmethod
    def _build_active_path(
        *,
        stage_status: dict[str, str],
        current_step_id: str | None,
    ) -> list[str]:
        path = [
            step_id
            for step_id, status in stage_status.items()
            if status in {"started", "completed", "failed", "waiting_user"}
        ]
        if current_step_id and current_step_id not in path:
            path.append(current_step_id)
        return path

    @staticmethod
    def _safe_non_negative_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return max(value, 0)
        return None

    @staticmethod
    def _citation_sort_key(citation_id: str) -> tuple[int, str]:
        normalized = citation_id.strip().upper()
        if normalized.startswith("S"):
            suffix = normalized[1:]
            if suffix.isdigit():
                return int(suffix), normalized
        return 10_000_000, normalized

    @staticmethod
    def _normalize_optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        return text or None

    @staticmethod
    def _extract_locator_material_title(locator: dict[str, Any] | None) -> str | None:
        if not isinstance(locator, dict):
            return None
        return KbChatService._normalize_optional_text(locator.get("material_title"))

    @staticmethod
    def _extract_filename_stem(locator: dict[str, Any] | None) -> str | None:
        if not isinstance(locator, dict):
            return None
        filename = locator.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            return None
        base = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        normalized = normalize_citation_label(stem)
        return normalized or None

    @staticmethod
    def _extract_citation_source(item: dict[str, Any]) -> str | None:
        direct = KbChatService._normalize_optional_text(item.get("citation_source"))
        if direct:
            return direct
        locator = item.get("locator")
        if not isinstance(locator, dict):
            return None
        filename = KbChatService._normalize_optional_text(locator.get("filename"))
        if filename:
            return filename
        return KbChatService._normalize_optional_text(locator.get("source"))

    @staticmethod
    def _extract_citation_title(item: dict[str, Any], *, fallback_index: int) -> str:
        material_title = KbChatService._normalize_optional_text(item.get("material_title"))
        if material_title:
            return material_title

        raw = item.get("citation_title")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        legacy_title = item.get("title")
        if isinstance(legacy_title, str) and legacy_title.strip():
            return legacy_title.strip()

        locator = item.get("locator")
        if isinstance(locator, dict):
            locator_material_title = KbChatService._extract_locator_material_title(locator)
            if locator_material_title:
                return locator_material_title
            label = locator.get("citation_label")
            if isinstance(label, str):
                normalized = normalize_citation_label(label)
                if normalized:
                    return normalized
            filename_stem = KbChatService._extract_filename_stem(locator)
            if filename_stem:
                return filename_stem
        return f"资料{fallback_index}"

    async def _load_material_title_map(
        self, material_ids: set[uuid.UUID]
    ) -> dict[str, str]:
        if not material_ids:
            return {}
        stmt = select(SourceMaterial.id, SourceMaterial.title).where(
            SourceMaterial.id.in_(list(material_ids))
        )
        result = await self._db.execute(stmt)
        title_map: dict[str, str] = {}
        for material_id, title in result.all():
            if isinstance(title, str) and title.strip():
                title_map[str(material_id)] = title.strip()
        return title_map

    @staticmethod
    def _extract_citation_page_hint(locator: dict[str, Any] | None) -> str | None:
        if not isinstance(locator, dict):
            return None
        page_start = locator.get("page_start")
        page_end = locator.get("page_end")
        if isinstance(page_start, int) and page_start > 0:
            if isinstance(page_end, int) and page_end > 0 and page_end != page_start:
                return f"p.{page_start}-{page_end}"
            return f"p.{page_start}"
        if isinstance(page_end, int) and page_end > 0:
            return f"p.{page_end}"
        return None

    @classmethod
    def _append_citation_sources(
        cls,
        answer: str,
        *,
        citation_catalog: dict[str, dict[str, Any]] | None,
        include_reference_section: bool = False,
    ) -> str:
        text = str(answer or "").strip()
        if (
            not include_reference_section
            or not text
            or not isinstance(citation_catalog, dict)
            or not citation_catalog
        ):
            return text

        used = [
            label.strip().upper()
            for label in extract_citation_labels(text)
            if is_stable_citation_id(label)
        ]
        if not used:
            return text

        ordered_ids: list[str] = []
        seen: set[str] = set()
        for citation_id in sorted(set(used), key=cls._citation_sort_key):
            if citation_id in seen:
                continue
            if citation_id not in citation_catalog:
                continue
            seen.add(citation_id)
            ordered_ids.append(citation_id)
        if not ordered_ids:
            return text

        lines = ["参考来源："]
        for idx, citation_id in enumerate(ordered_ids, 1):
            item = citation_catalog[citation_id]
            title = cls._extract_citation_title(item, fallback_index=idx)
            locator = item.get("locator")
            page_hint = cls._extract_citation_page_hint(locator if isinstance(locator, dict) else None)
            if page_hint:
                lines.append(f"[{citation_id}] {title}（{page_hint}）")
            else:
                lines.append(f"[{citation_id}] {title}")

        return f"{text}\n\n" + "\n".join(lines)

    @classmethod
    def _resolve_preferred_evidence_round(
        cls,
        *,
        stage_summaries: dict[str, Any],
        loop_counts: dict[str, Any] | None,
    ) -> int | None:
        force_exit = (
            stage_summaries.get("force_exit")
            if isinstance(stage_summaries, dict)
            else None
        )
        if isinstance(force_exit, dict):
            best_meta = force_exit.get("best_answer_meta")
            if isinstance(best_meta, dict):
                round_value = cls._safe_non_negative_int(best_meta.get("retrieval_round"))
                if round_value is not None:
                    return round_value

        answer_review = (
            stage_summaries.get("answer_review")
            if isinstance(stage_summaries, dict)
            else None
        )
        if isinstance(answer_review, dict):
            best_meta = answer_review.get("best_answer_meta")
            if isinstance(best_meta, dict):
                round_value = cls._safe_non_negative_int(best_meta.get("retrieval_round"))
                if round_value is not None:
                    return round_value

        if isinstance(loop_counts, dict):
            round_value = cls._safe_non_negative_int(loop_counts.get("retrieval_retries"))
            if round_value is not None:
                return round_value
        return None

    @staticmethod
    def _select_evidence_draft_items(
        *,
        evidence_draft_items_by_round: dict[int, list[dict[str, Any]]] | None,
        preferred_round: int | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(evidence_draft_items_by_round, dict) or not evidence_draft_items_by_round:
            return []
        if preferred_round is not None:
            items = evidence_draft_items_by_round.get(preferred_round)
            if isinstance(items, list):
                return list(items)
            return []
        available_rounds = [k for k in evidence_draft_items_by_round if isinstance(k, int)]
        if not available_rounds:
            return []
        latest_round = max(available_rounds)
        items = evidence_draft_items_by_round.get(latest_round)
        return list(items) if isinstance(items, list) else []

    @staticmethod
    def _extract_last_good_answer(
        *,
        answer: str,
        stage_summaries: dict[str, Any],
        stream_state: StreamState,
    ) -> tuple[str | None, str | None]:
        answer_text = extract_answer_text(answer).strip()
        if answer_text:
            return answer_text, "final_answer"

        for msg in reversed(stream_state.messages):
            if isinstance(msg, AIMessage):
                text = extract_answer_text(msg.content).strip()
                if text:
                    return text, "ai_message"

        best_answer = stream_state.best_answer
        if isinstance(best_answer, str) and best_answer.strip():
            return best_answer.strip(), "stream_state.best_answer"

        force_exit = (
            stage_summaries.get("force_exit")
            if isinstance(stage_summaries, dict)
            else None
        )
        if isinstance(force_exit, dict):
            best_answer = force_exit.get("best_answer")
            if isinstance(best_answer, str) and best_answer.strip():
                return best_answer.strip(), "force_exit.best_answer"

        answer_review = (
            stage_summaries.get("answer_review")
            if isinstance(stage_summaries, dict)
            else None
        )
        if isinstance(answer_review, dict):
            best_answer = answer_review.get("best_answer")
            if isinstance(best_answer, str) and best_answer.strip():
                return best_answer.strip(), "answer_review.best_answer"

        generator = (
            stage_summaries.get("generator")
            if isinstance(stage_summaries, dict)
            else None
        )
        if isinstance(generator, dict):
            draft_answer = generator.get("draft_answer")
            if isinstance(draft_answer, str) and draft_answer.strip():
                return draft_answer.strip(), "generator.draft_answer"

        return None, None

    @staticmethod
    def _clarification_round_count(stage_summaries: dict[str, Any] | None) -> int:
        if not isinstance(stage_summaries, dict):
            return 0
        entry = stage_summaries.get("clarification_pending")
        if isinstance(entry, dict):
            value = entry.get("round")
            if isinstance(value, int) and value > 0:
                return value
        return 0

    async def _persist_clarification_pending(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
        started_at: datetime,
        message: str,
        pending_clarification: PendingClarification | None,
        stage_summaries: dict[str, Any],
        metrics: dict[str, Any],
    ) -> ChatPendingUserClarificationResponse:
        now = datetime.now(timezone.utc)
        round_count = self._clarification_round_count(
            run.stage_summaries if isinstance(run.stage_summaries, dict) else None
        ) + 1
        payload_dict = (
            pending_clarification.model_dump(mode="json")
            if isinstance(pending_clarification, PendingClarification)
            else None
        )
        stage_summaries = {
            **(stage_summaries if isinstance(stage_summaries, dict) else {}),
            "clarification_pending": {
                "pending": True,
                "round": round_count,
                "message": message,
                "pending_clarification": payload_dict,
                "requested_at": now.isoformat(),
            },
        }
        stage_summaries = ensure_json_safe(
            stage_summaries, settings=self._settings, label="stage_summaries"
        )

        metrics = ensure_json_safe(
            metrics if isinstance(metrics, dict) else {},
            settings=self._settings,
            label="metrics",
        )
        run.status = AgentRunStatus.RUNNING
        run.finished_at = None
        run.final_output = None
        run.error_message = None
        run.stage_summaries = stage_summaries
        run.metrics = {
            **metrics,
            "latency_ms": int((now - started_at).total_seconds() * 1000),
            "clarification_pending": True,
            "clarification_round": round_count,
            "ambiguity_triggered": True,
        }

        await self._db.commit()
        await self._db.refresh(run)
        return ChatPendingUserClarificationResponse(
            thread_id=str(session.id),
            message=message,
            pending_clarification=pending_clarification,
            run=AgentRunRead.model_validate(run),
        )

    async def answer(
        self,
        *,
        session: ChatSession,
        user_content: str,
        run: AgentRun | None = None,
    ) -> ChatAnswerResponse | ChatPendingUserClarificationResponse:
        "处理用户问题并生成答案（使用 LangGraph）。"
        exec_ctx = await self._prepare_kb_chat_execution(
            session=session, user_content=user_content, run=run
        )
        run = exec_ctx.run

        try:
            store = None
            try:
                store = StoreManager.get_store()
            except Exception:
                store = None

            result = await exec_ctx.graph.run(
                exec_ctx.state,
                thread_id=exec_ctx.thread_id,
                checkpointer=CheckpointManager.get_checkpointer(),
                store=store,
            )

            if not isinstance(result, dict):
                raise RuntimeError("LangGraph 返回类型不符合预期")

            self._ensure_no_pending_tool_approval(
                pending_tool_calls=result.get("pending_tool_calls"),
                interrupts=result.get("__interrupt__"),
            )

            answer = ""
            result_messages = result.get("messages")
            if isinstance(result_messages, list):
                for msg in reversed(result_messages):
                    if isinstance(msg, AIMessage):
                        answer = str(msg.content or "")
                        break

            metrics, stage_summaries = self._build_observability(
                kb_chat_config=exec_ctx.kb_chat_config,
                history_usage=exec_ctx.history_usage,
                history_truncation=exec_ctx.history_truncation,
                retrieval_meta=exec_ctx.retrieval_meta,
                retrieval_results=exec_ctx.retrieval_results,
                base_metrics=result.get("metrics")
                if isinstance(result.get("metrics"), dict)
                else {},
                base_stage_summaries=result.get("stage_summaries")
                if isinstance(result.get("stage_summaries"), dict)
                else {},
            )
            metrics = self._apply_guardrail_metrics(
                metrics=metrics,
                stage_summaries=stage_summaries,
                kb_scope=exec_ctx.retrieval_meta.get("kb_scope")
                if isinstance(exec_ctx.retrieval_meta, dict)
                else None,
            )

            clarification_message, pending_clarification = self._extract_clarification_pending(
                stage_summaries=stage_summaries,
                answer=answer,
            )
            if clarification_message is not None:
                max_rounds = max(
                    0,
                    int(getattr(self._settings, "kb_chat_max_clarification_rounds", 1)),
                )
                current_rounds = self._clarification_round_count(
                    run.stage_summaries if isinstance(run.stage_summaries, dict) else None
                )
                if current_rounds < max_rounds:
                    return await self._persist_clarification_pending(
                        session=session,
                        run=run,
                        started_at=exec_ctx.started_at,
                        message=clarification_message,
                        pending_clarification=pending_clarification,
                        stage_summaries=stage_summaries,
                        metrics=metrics,
                    )
                stage_summaries = {
                    **stage_summaries,
                    "clarification_pending": {
                        "pending": False,
                        "round": current_rounds,
                        "max_rounds": max_rounds,
                        "max_rounds_reached": True,
                        "message": clarification_message,
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
                answer = (
                    "基于当前对话信息仍存在关键歧义，暂时无法给出可靠结论。"
                    "请在下一次提问时明确对象、范围与时间。"
                )

            terminal_status, terminal_message = self._resolve_terminal_run_status(
                stage_summaries=stage_summaries,
                answer=answer,
            )
            preferred_evidence_round = self._resolve_preferred_evidence_round(
                stage_summaries=stage_summaries,
                loop_counts=result.get("loop_counts")
                if isinstance(result.get("loop_counts"), dict)
                else None,
            )
            return await self._finalize_run(
                session=session,
                run=run,
                started_at=exec_ctx.started_at,
                answer=answer,
                retrieval_results=exec_ctx.retrieval_results,
                evidence_draft_items_by_round=exec_ctx.evidence_draft_items_by_round,
                preferred_evidence_round=preferred_evidence_round,
                stage_summaries=stage_summaries,
                metrics=metrics,
                status=terminal_status,
                error_message=terminal_message,
            )

        except asyncio.CancelledError:
            await self._persist_guardrail_run(
                exec_ctx=exec_ctx,
                run=run,
                status=AgentRunStatus.CANCELED,
                reason="canceled",
            )
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
        run: AgentRun | None = None,
    ) -> Any:
        """处理用户问题并返回流式 SSE（状态与节点事件基于 LangGraph 原生流）。"""
        exec_ctx = await self._prepare_kb_chat_execution(
            session=session, user_content=user_content, run=run
        )
        run = exec_ctx.run
        graph_task: asyncio.Task | None = None
        disconnect_task: asyncio.Task | None = None

        stream_state = StreamState(
            messages=list(exec_ctx.state.get("messages") or []),
            pending_tool_calls=list(exec_ctx.state.get("pending_tool_calls") or []),
            stage_summaries=dict(exec_ctx.state.get("stage_summaries") or {}),
            metrics=dict(exec_ctx.state.get("metrics") or {}),
            loop_counts=dict(exec_ctx.state.get("loop_counts") or {}),
        )

        def _emit_enveloped(
            *,
            event_type: str,
            payload: dict[str, Any],
            node_name: str | None = None,
        ) -> tuple[str, dict[str, Any]]:
            node = None
            if isinstance(node_name, str) and node_name:
                node = {"id": node_name, "name": node_name}
            return (
                event_type,
                self._build_protocol_event_payload(
                    event_type=event_type,
                    run_id=run.id,
                    payload=payload,
                    node=node,
                ),
            )

        def _emit_ui_event(
            *,
            event_type: str,
            message: str | None = None,
            candidate_answer: str | None = None,
            source_step_id: str | None = None,
            degrade_reason_value: str | None = None,
        ) -> tuple[str, dict[str, Any]]:
            payload: dict[str, Any] = {
                "event_type": event_type,
                "run_id": str(run.id),
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if message is not None:
                payload["message"] = message
            if candidate_answer is not None:
                payload["candidate_answer"] = candidate_answer
            if source_step_id is not None:
                payload["source_step_id"] = source_step_id
            if degrade_reason_value is not None:
                payload["degrade_reason"] = degrade_reason_value
            return _emit_enveloped(event_type="ui_event", payload=payload)

        async def _cancel_graph() -> None:
            if graph_task is None or graph_task.done():
                return
            graph_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await graph_task

        try:
            yield (
                "meta",
                self._build_protocol_event_payload(
                    event_type="meta",
                    run_id=run.id,
                    payload={
                        "run_id": str(run.id),
                        "session_id": str(session.id),
                        "session_type": session.session_type.value,
                        "thread_id": exec_ctx.thread_id,
                        "mode": session.mode.value,
                    },
                ),
            )

            store = None
            try:
                store = StoreManager.get_store()
            except Exception:
                store = None
            compiled = exec_ctx.graph.compile(
                checkpointer=CheckpointManager.get_checkpointer(),
                store=store,
            )
            make_run_config = getattr(exec_ctx.graph, "make_run_config", None)
            if callable(make_run_config):
                config = make_run_config(thread_id=exec_ctx.thread_id)
            else:
                config = CheckpointManager.make_config(exec_ctx.thread_id)
            stream = compiled.astream(
                exec_ctx.state,
                config,
                stream_mode=["messages", "updates", "custom"],
                subgraphs=True,
            )

            queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
            disconnect_event = asyncio.Event()

            async def _run_graph() -> None:
                try:
                    async for raw_event in stream:
                        normalized = self._normalize_graph_stream_event(raw_event)
                        if normalized is None:
                            continue
                        await queue.put(("event", normalized))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await queue.put(("error", exc))
                finally:
                    await queue.put(("done", None))
                    try:
                        await stream.aclose()
                    except Exception:
                        pass

            async def _monitor_disconnect() -> None:
                if request is None:
                    return
                is_disconnected = getattr(request, "is_disconnected", None)
                if not callable(is_disconnected):
                    return
                while True:
                    if await is_disconnected():
                        disconnect_event.set()
                        return
                    await asyncio.sleep(0.2)

            graph_task = asyncio.create_task(_run_graph())
            disconnect_task = (
                asyncio.create_task(_monitor_disconnect()) if request is not None else None
            )

            last_good_answer: str | None = None
            last_good_answer_source: str | None = None

            while True:
                if disconnect_event.is_set():
                    await _cancel_graph()
                    await self._persist_guardrail_run(
                        exec_ctx=exec_ctx,
                        run=run,
                        status=AgentRunStatus.CANCELED,
                        reason="canceled",
                        stream_state=stream_state,
                    )
                    yield (
                        "error",
                        {
                            "code": "CHAT_STREAM_CANCELED",
                            "message": "client disconnected",
                        },
                    )
                    return

                queue_task = asyncio.create_task(queue.get())
                wait_tasks = {queue_task}
                if disconnect_task is not None:
                    wait_tasks.add(disconnect_task)
                done, _pending = await asyncio.wait(
                    wait_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if disconnect_task is not None and disconnect_task in done:
                    if disconnect_event.is_set():
                        if not queue_task.done():
                            queue_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await queue_task
                        await _cancel_graph()
                        await self._persist_guardrail_run(
                            exec_ctx=exec_ctx,
                            run=run,
                            status=AgentRunStatus.CANCELED,
                            reason="canceled",
                            stream_state=stream_state,
                        )
                        yield (
                            "error",
                            {
                                "code": "CHAT_STREAM_CANCELED",
                                "message": "client disconnected",
                            },
                        )
                        return
                    disconnect_task = None

                if queue_task not in done:
                    continue

                kind, payload = queue_task.result()
                if kind == "event":
                    mode, chunk = payload

                    if mode == "messages":
                        token = None
                        token_meta: dict[str, Any] | None = None
                        if isinstance(chunk, tuple) and len(chunk) == 2:
                            token = chunk[0]
                            if isinstance(chunk[1], dict):
                                token_meta = chunk[1]
                        elif isinstance(chunk, list) and len(chunk) == 2:
                            token = chunk[0]
                            if isinstance(chunk[1], dict):
                                token_meta = chunk[1]
                        else:
                            token = chunk

                        deltas = extract_stream_delta(
                            token,
                            token_meta,
                        )
                        if deltas:
                            node_name = (
                                token_meta.get("langgraph_node")
                                if isinstance(token_meta, dict)
                                and isinstance(token_meta.get("langgraph_node"), str)
                                else None
                            )
                            yield _emit_enveloped(
                                event_type="messages",
                                payload={
                                    "run_id": str(run.id),
                                    "node": node_name,
                                    "deltas": [delta.to_dict() for delta in deltas],
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                },
                                node_name=node_name,
                            )
                        continue

                    if mode == "updates" and isinstance(chunk, dict):
                        candidate_node = next(
                            (
                                source
                                for source in chunk.keys()
                                if isinstance(source, str) and source != "__interrupt__"
                            ),
                            None,
                        )
                        interrupts = apply_updates_chunk(stream_state, chunk)
                        candidate, candidate_source = self._extract_last_good_answer(
                            answer="",
                            stage_summaries=stream_state.stage_summaries
                            if isinstance(stream_state.stage_summaries, dict)
                            else {},
                            stream_state=stream_state,
                        )
                        if candidate:
                            last_good_answer = candidate
                            last_good_answer_source = candidate_source
                        self._ensure_no_pending_tool_approval(
                            pending_tool_calls=stream_state.pending_tool_calls,
                            interrupts=interrupts,
                        )
                        yield _emit_enveloped(
                            event_type="updates",
                            payload={
                                "run_id": str(run.id),
                                "chunk": chunk,
                                "ts": datetime.now(timezone.utc).isoformat(),
                            },
                            node_name=candidate_node,
                        )
                        continue

                    if mode == "custom":
                        safe_payload = self._json_safe_custom_payload(chunk)
                        if isinstance(safe_payload, dict):
                            node_name = (
                                safe_payload.get("node_name")
                                if isinstance(safe_payload.get("node_name"), str)
                                else None
                            )
                            payload_dict = dict(safe_payload)
                            payload_dict.setdefault("run_id", str(run.id))
                            payload_dict.setdefault(
                                "ts", datetime.now(timezone.utc).isoformat()
                            )
                            yield _emit_enveloped(
                                event_type="custom",
                                payload=payload_dict,
                                node_name=node_name,
                            )
                        continue

                    continue

                if kind == "error":
                    raise payload
                if kind == "done":
                    break

            self._ensure_no_pending_tool_approval(
                pending_tool_calls=stream_state.pending_tool_calls,
                interrupts=None,
            )

            answer = ""
            for msg in reversed(stream_state.messages):
                if isinstance(msg, AIMessage):
                    answer = extract_answer_text(msg.content)
                    break

            metrics, stage_summaries = self._build_observability(
                kb_chat_config=exec_ctx.kb_chat_config,
                history_usage=exec_ctx.history_usage,
                history_truncation=exec_ctx.history_truncation,
                retrieval_meta=exec_ctx.retrieval_meta,
                retrieval_results=exec_ctx.retrieval_results,
                base_metrics=stream_state.metrics,
                base_stage_summaries=stream_state.stage_summaries,
            )
            metrics = self._apply_guardrail_metrics(
                metrics=metrics,
                stage_summaries=stage_summaries,
                kb_scope=exec_ctx.retrieval_meta.get("kb_scope")
                if isinstance(exec_ctx.retrieval_meta, dict)
                else None,
            )

            clarification_message, pending_clarification = self._extract_clarification_pending(
                stage_summaries=stage_summaries,
                answer=answer,
            )
            candidate, candidate_source = self._extract_last_good_answer(
                answer=answer,
                stage_summaries=stage_summaries,
                stream_state=stream_state,
            )
            if candidate:
                last_good_answer = candidate
                last_good_answer_source = candidate_source

            if clarification_message is not None:
                max_rounds = max(
                    0,
                    int(getattr(self._settings, "kb_chat_max_clarification_rounds", 1)),
                )
                current_rounds = self._clarification_round_count(
                    run.stage_summaries if isinstance(run.stage_summaries, dict) else None
                )
                if current_rounds < max_rounds:
                    if last_good_answer:
                        yield _emit_ui_event(
                            event_type="candidate_answer_updated",
                            candidate_answer=last_good_answer,
                            source_step_id=last_good_answer_source,
                        )
                    pending_response = await self._persist_clarification_pending(
                        session=session,
                        run=run,
                        started_at=exec_ctx.started_at,
                        message=clarification_message,
                        pending_clarification=pending_clarification,
                        stage_summaries=stage_summaries,
                        metrics=metrics,
                    )
                    yield "interrupt", pending_response.model_dump(mode="json")
                    return
                stage_summaries = {
                    **stage_summaries,
                    "clarification_pending": {
                        "pending": False,
                        "round": current_rounds,
                        "max_rounds": max_rounds,
                        "max_rounds_reached": True,
                        "message": clarification_message,
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
                answer = (
                    "基于当前对话信息仍存在关键歧义，暂时无法给出可靠结论。"
                    "请在下一次提问时明确对象、范围与时间。"
                )

            terminal_status, terminal_message = self._resolve_terminal_run_status(
                stage_summaries=stage_summaries,
                answer=answer,
            )
            if terminal_status == AgentRunStatus.FAILED and last_good_answer:
                yield _emit_ui_event(
                    event_type="degraded_to_candidate",
                    message="最终回答失败，已回退展示候选答案。",
                    candidate_answer=last_good_answer,
                    source_step_id=last_good_answer_source,
                    degrade_reason_value=terminal_message,
                )

            preferred_evidence_round = self._resolve_preferred_evidence_round(
                stage_summaries=stage_summaries,
                loop_counts=stream_state.loop_counts,
            )
            final_response = await self._finalize_run(
                session=session,
                run=run,
                started_at=exec_ctx.started_at,
                answer=answer,
                retrieval_results=exec_ctx.retrieval_results,
                evidence_draft_items_by_round=exec_ctx.evidence_draft_items_by_round,
                preferred_evidence_round=preferred_evidence_round,
                stage_summaries=stage_summaries,
                metrics=metrics,
                status=terminal_status,
                error_message=terminal_message,
            )
            yield "final", final_response.model_dump(mode="json")

        except asyncio.CancelledError:
            await _cancel_graph()
            await self._persist_guardrail_run(
                exec_ctx=exec_ctx,
                run=run,
                status=AgentRunStatus.CANCELED,
                reason="canceled",
                stream_state=stream_state,
            )
            raise
        except Exception as e:
            await _cancel_graph()
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = e.message if isinstance(e, AppError) else str(e)
            await self._db.commit()
            if isinstance(e, AppError):
                yield (
                    "error",
                    {
                        "code": e.code,
                        "message": e.message,
                        "details": e.details,
                    },
                )
                return
            yield (
                "error",
                {
                    "code": "CHAT_STREAM_FAILED",
                    "message": str(e),
                },
            )
        finally:
            if disconnect_task is not None:
                disconnect_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await disconnect_task
            set_run_id(None)

    async def _finalize_run(

        self,
        *,
        session: ChatSession,
        run: AgentRun,
        started_at: datetime,
        answer: str,
        retrieval_results: list,
        evidence_draft_items_by_round: dict[int, list[dict[str, Any]]] | None = None,
        preferred_evidence_round: int | None = None,
        stage_summaries: dict[str, Any],
        metrics: dict[str, Any],
        status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
        error_message: str | None = None,
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
        citation_catalog: dict[str, dict[str, Any]] = {}
        citation_id_by_chunk_id: dict[str, str] = {}
        selected_evidence_draft_items = self._select_evidence_draft_items(
            evidence_draft_items_by_round=evidence_draft_items_by_round,
            preferred_round=preferred_evidence_round,
        )
        should_fallback_to_retrieval_results = (
            not selected_evidence_draft_items and preferred_evidence_round is None
        )

        if selected_evidence_draft_items:
            for it in selected_evidence_draft_items:
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
                if source_kind == EvidenceSourceKind.KB and (
                    chunk_id is None or kb_id is None or material_id is None
                ):
                    # KB evidence must be chunk-traceable.
                    continue

                excerpt = str(it.get("excerpt") or "")[:500]
                if not excerpt.strip():
                    continue

                locator = (
                    it.get("locator") if isinstance(it.get("locator"), dict) else None
                )
                raw_citation_id = it.get("citation_id")
                citation_id = (
                    str(raw_citation_id).strip().upper()
                    if isinstance(raw_citation_id, str)
                    else ""
                )
                if is_stable_citation_id(citation_id):
                    citation_catalog[citation_id] = {
                        "citation_id": citation_id,
                        "material_title": self._normalize_optional_text(
                            it.get("material_title")
                        ),
                        "citation_title": it.get("citation_title"),
                        "citation_source": it.get("citation_source"),
                        "locator": locator,
                        "chunk_id": str(chunk_id) if chunk_id else None,
                        "material_id": str(material_id) if material_id else None,
                        "kb_id": str(kb_id) if kb_id else None,
                    }
                    if chunk_id:
                        citation_id_by_chunk_id[str(chunk_id)] = citation_id

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
                        citation_id=citation_id if is_stable_citation_id(citation_id) else None,
                        citation_title=self._normalize_optional_text(
                            it.get("citation_title")
                        ),
                        citation_source=self._normalize_optional_text(
                            it.get("citation_source")
                        ),
                    )
                )
                if chunk_id:
                    seen_evidence_chunk_ids.add(chunk_id)
        elif should_fallback_to_retrieval_results:
            for idx, r in enumerate(retrieval_results, 1):
                citation_id = f"S{idx}"
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
                        citation_id=citation_id,
                    )
                )
                locator = r.chunk.locator if isinstance(r.chunk.locator, dict) else None
                citation_catalog[citation_id] = {
                    "citation_id": citation_id,
                    "material_title": self._extract_locator_material_title(locator),
                    "citation_title": None,
                    "citation_source": None,
                    "locator": locator,
                    "chunk_id": str(r.chunk.id),
                    "material_id": str(r.chunk.material_id),
                    "kb_id": str(r.chunk.kb_id),
                }
                citation_id_by_chunk_id[str(r.chunk.id)] = citation_id

        material_ids: set[uuid.UUID] = set()
        for item in citation_catalog.values():
            material_id = _parse_uuid(item.get("material_id"))
            if material_id:
                material_ids.add(material_id)
        for item in evidence_items:
            if item.material_id is not None:
                material_ids.add(item.material_id)

        material_title_map = await self._load_material_title_map(material_ids)

        citation_meta_by_id: dict[str, dict[str, str | None]] = {}
        ordered_citation_ids = sorted(citation_catalog, key=self._citation_sort_key)
        for idx, citation_id in enumerate(ordered_citation_ids, 1):
            item = citation_catalog[citation_id]
            material_id_text = self._normalize_optional_text(item.get("material_id"))
            if material_id_text:
                material_title = material_title_map.get(material_id_text)
                if material_title:
                    item["material_title"] = material_title

            locator = item.get("locator") if isinstance(item.get("locator"), dict) else None
            if self._extract_locator_material_title(locator):
                item["material_title"] = self._extract_locator_material_title(locator)

            citation_title = self._extract_citation_title(item, fallback_index=idx)
            citation_page_hint = self._extract_citation_page_hint(locator)
            citation_source = self._extract_citation_source(item)

            item["citation_title"] = citation_title
            item["citation_page_hint"] = citation_page_hint
            item["citation_source"] = citation_source
            citation_meta_by_id[citation_id] = {
                "citation_title": citation_title,
                "citation_page_hint": citation_page_hint,
                "citation_source": citation_source,
            }

        for item in evidence_items:
            raw_citation_id = self._normalize_optional_text(item.citation_id)
            citation_id = raw_citation_id.upper() if raw_citation_id else None
            if not citation_id and item.chunk_id is not None:
                citation_id = citation_id_by_chunk_id.get(str(item.chunk_id))
            if not citation_id:
                continue
            meta = citation_meta_by_id.get(citation_id)
            if meta is None:
                continue
            item.citation_id = citation_id
            item.citation_title = meta.get("citation_title")
            item.citation_page_hint = meta.get("citation_page_hint")
            item.citation_source = meta.get("citation_source")

        def _label_from_locator(locator: dict | None) -> str | None:
            if not isinstance(locator, dict):
                return None
            raw = locator.get("citation_label")
            if isinstance(raw, str):
                text = " ".join(raw.replace("[", " ").replace("]", " ").split()).strip()
                if text:
                    return text
            filename = locator.get("filename")
            if isinstance(filename, str) and filename.strip():
                base = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
                stem = base.rsplit(".", 1)[0] if "." in base else base
                normalized = " ".join(stem.replace("[", " ").replace("]", " ").split())
                if normalized:
                    return normalized
            return None

        allowed_labels: list[str] = sorted(citation_catalog, key=self._citation_sort_key)
        if not allowed_labels:
            seen_labels: set[str] = set()
            for item in evidence_items:
                label = _label_from_locator(
                    item.locator if isinstance(item.locator, dict) else None
                )
                if not label:
                    continue
                key = label.casefold()
                if key in seen_labels:
                    continue
                seen_labels.add(key)
                allowed_labels.append(label)

        # 强约束：引用必须与证据标签一致；无证据（非澄清）时禁止输出看似引用标签。
        force_exit = (
            stage_summaries.get("force_exit")
            if isinstance(stage_summaries, dict)
            else None
        )
        allow_no_evidence = (
            isinstance(force_exit, dict) and force_exit.get("reason") == "clarify"
        )
        answer = enforce_kb_answer_citation_guardrails(
            answer,
            allowed_labels=allowed_labels,
            allow_no_evidence=allow_no_evidence,
        )
        answer = self._append_citation_sources(
            answer,
            citation_catalog=citation_catalog,
            include_reference_section=False,
        )
        no_evidence_answer = "根据现有资料无法回答该问题（未检索到相关证据）。"
        if (
            not allow_no_evidence
            and len(evidence_items) == 0
            and answer.strip() == no_evidence_answer
        ):
            answer = self._build_no_evidence_response(
                stage_summaries=stage_summaries
                if isinstance(stage_summaries, dict)
                else {},
                selected_kb_ids=session.selected_kb_ids,
            )

        # Best-effort: write a small, structured memory entry (bounded + TTL).
        if status == AgentRunStatus.SUCCEEDED and self._settings.memory_enabled:
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
        if status == AgentRunStatus.SUCCEEDED:
            try:
                summary_result = await self._summary_service.maybe_update_summary(
                    session.id
                )
                if summary_result:
                    summary_metrics = {
                        "summary_updated": True,
                        **summary_result.stats,
                    }
            except Exception as exc:  # pragma: no cover
                logger.warning("摘要更新失败: %s", exc)

        # 更新运行状态
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.final_output = answer
        run.error_message = (
            None if status == AgentRunStatus.SUCCEEDED else (error_message or "")
        )
        stage_summaries = ensure_json_safe(
            stage_summaries, settings=self._settings, label="stage_summaries"
        )
        metrics = ensure_json_safe(metrics, settings=self._settings, label="metrics")
        run.stage_summaries = stage_summaries
        run.metrics = {
            "evidence_count": len(evidence_items),
            "evidence_chunk_ids": [
                str(item.chunk_id)
                for item in evidence_items
                if item.chunk_id is not None
            ],
            "citation_ids": sorted(citation_catalog, key=self._citation_sort_key),
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
