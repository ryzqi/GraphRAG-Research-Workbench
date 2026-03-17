"""知识库问答服务。

使用 LangGraph 图实现，支持检查点持久化。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kb_chat_agentic.json_safety import ensure_json_safe
from app.agents.kb_chat_graph import build_kb_chat_graph
from app.agents.kb_chat_memory import (
    append_kb_chat_memory_entry,
    resolve_kb_chat_store_user_id,
)
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
from app.models.knowledge_base import KnowledgeBase
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
    SemanticCacheMeta,
    resolve_kb_chat_config,
)
from app.api.sse import SseHeartbeatStats
from app.services.context_builder import ContextBuilder
from app.services.conversation_summary_service import ConversationSummaryService
from app.services.evidence_guardrails import (
    enforce_kb_answer_citation_guardrails,
    extract_citation_labels,
    is_kb_refusal_answer,
    is_stable_citation_id,
    normalize_citation_label,
    resolve_kb_refusal_answer,
)
from app.services.retrieval_service import RetrievalService
from app.services.streaming import (
    StreamState,
    apply_updates_chunk,
    extract_answer_text,
    extract_stream_delta,
)
from app.agents.kb_chat_contracts import (
    KB_CHAT_CUSTOM_EVENT_TYPES,
    STATE_SCHEMA_V3,
    validate_event_envelope_v2,
)
from app.agents.kb_chat_agentic_state import (
    build_graph_input_state,
    resolve_terminal_routing_decision,
)

logger = logging.getLogger(__name__)
_STREAM_EVENT_VERSION = "2.0"
_GRAY_ROUTE_THRESHOLD = 99.5
_GRAY_FINAL_THRESHOLD = 99.0
_GRAY_CLARIFICATION_THRESHOLD = 99.0
_GRAY_P95_THRESHOLD = 10.0
_KB_CHAT_CHECKPOINT_RESET_FIELDS = (
    "user_input",
    "pending_tool_calls",
    "context_frame",
    "rewrite_input_query",
    "merged_context",
    "coref_query",
    "coref_meta",
    "normalized_query",
    "normalized_meta",
    "entity_expand_meta",
    "query_strategy",
    "complexity_level",
    "query_strategy_confidence",
    "query_strategy_signals",
    "decomposition_plan",
    "sub_queries",
    "multi_queries",
    "hyde_docs",
    "message_plan",
    "query_bundle",
    "prepare_diagnostics",
    "preprocess_next",
    "retrieval_plan",
    "retrieval_budget",
    "retrieval_diagnostics",
    "query_items",
    "subquery_runs",
    "subquery_task",
    "final_context",
    "compression_stats",
    "draft_answer",
    "final_answer",
    "best_answer",
    "best_answer_meta",
    "answer_subgraph_state",
    "answer_quality",
    "degrade_reason",
    "clarification_payload",
    "doc_gate_state",
    "doc_gate_round",
    "doc_gate_runs",
    "doc_gate_scores",
    "answer_review_runs",
    "cove_state",
    "confidence_score",
    "confidence_level",
    "reflection",
    "routing_decisions",
)


def _gray_release_log_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "logs" / "kb_chat_gray_release"


@dataclass
class _KbRetrievalBuffer:
    results: list
    evidence_by_round: dict[int, list[dict[str, Any]]]
    meta: dict[str, Any]

    def release(self) -> None:
        self.results.clear()
        self.evidence_by_round.clear()
        self.meta.clear()


@dataclass
class _SemanticCacheHit:
    answer: str
    evidence: list[dict[str, Any]]
    confidence_score: float | None
    confidence_level: str | None
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]
    score: float
    threshold: float
    ttl_seconds: int


@dataclass(frozen=True)
class _CheckpointRestorePlan:
    messages: list[SystemMessage | HumanMessage | AIMessage]
    reset_fields: list[str]
    legacy_fields: list[str]
    schema_supported: bool


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
    retrieval_buffer: _KbRetrievalBuffer
    graph: object
    compiled_graph: object | None
    state: dict[str, Any]
    run_context: dict[str, Any] | None
    resume_checkpoint_id: str | None


@dataclass
class _KbChatStreamRunState:
    stage_status: dict[str, str]
    stage_attempts: dict[str, int]
    current_step_id: str | None = None
    current_node: str | None = None
    state_version: int = 0
    latest_execution_by_scope: dict[tuple[tuple[str, ...], str], str] = field(
        default_factory=dict
    )


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
        self._embedding = embedding
        self._redis = redis
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
            "retrieval_top_k": int(config.retrieval_top_k),
            "retrieval_rerank_top_k": int(config.retrieval_rerank_top_k),
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

    def _semantic_cache_enabled(self) -> bool:
        return bool(getattr(self._settings, "kb_chat_semantic_cache_enabled", True))

    def _semantic_cache_threshold(self) -> float:
        return max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        self._settings,
                        "kb_chat_semantic_cache_similarity_threshold",
                        0.88,
                    )
                ),
            ),
        )

    def _semantic_cache_ttl_seconds(self) -> int:
        return max(
            0,
            int(getattr(self._settings, "kb_chat_semantic_cache_ttl_seconds", 24 * 60 * 60)),
        )

    def _semantic_cache_max_items(self) -> int:
        return max(
            1,
            int(getattr(self._settings, "kb_chat_semantic_cache_max_items", 128)),
        )

    @staticmethod
    def _semantic_config_fingerprint(config: KbChatConfig) -> str:
        raw = json.dumps(config.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    async def _semantic_kb_version(self, session: ChatSession) -> str:
        kb_ids = [uuid.UUID(str(kid)) for kid in (session.selected_kb_ids or [])]
        if not kb_ids:
            return "kb_none"
        stmt = (
            select(KnowledgeBase.id, KnowledgeBase.updated_at)
            .where(KnowledgeBase.id.in_(kb_ids))
            .order_by(KnowledgeBase.id.asc())
        )
        rows = (await self._db.execute(stmt)).all()
        payload: list[dict[str, str]] = [
            {"id": str(kid), "updated_at": ""} for kid in sorted(kb_ids, key=str)
        ]
        index_by_id = {item["id"]: idx for idx, item in enumerate(payload)}
        for row in rows:
            updated_at = row[1]
            kb_id = str(row[0])
            idx = index_by_id.get(kb_id)
            if idx is None:
                continue
            payload[idx] = {
                "id": kb_id,
                "updated_at": (
                    updated_at.isoformat()
                    if isinstance(updated_at, datetime)
                    else ""
                ),
            }
        payload_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload_raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _semantic_cache_key(
        session: ChatSession,
        *,
        config_fingerprint: str,
        kb_version: str,
    ) -> str:
        kb_ids = sorted(str(kid) for kid in (session.selected_kb_ids or []))
        mode_value = getattr(getattr(session, "mode", None), "value", None)
        scope = {
            "kb_ids": kb_ids,
            "allow_external": bool(getattr(session, "allow_external", False)),
            "mode": str(mode_value) if isinstance(mode_value, str) else str(mode_value or ""),
            "config_fingerprint": config_fingerprint,
            "kb_version": kb_version,
        }
        raw = json.dumps(scope, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        return f"kb_chat:semantic_cache:v2:{digest}"

    @staticmethod
    def _as_float_vector(value: Any) -> list[float] | None:
        if not isinstance(value, list) or not value:
            return None
        result: list[float] = []
        for item in value:
            if isinstance(item, bool):
                return None
            if not isinstance(item, (int, float)):
                return None
            result.append(float(item))
        return result if result else None

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = 0.0
        left_norm = 0.0
        right_norm = 0.0
        for l_value, r_value in zip(left, right, strict=False):
            dot += l_value * r_value
            left_norm += l_value * l_value
            right_norm += r_value * r_value
        if left_norm <= 0.0 or right_norm <= 0.0:
            return 0.0
        return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))

    async def _semantic_cache_lookup(
        self,
        *,
        session: ChatSession,
        kb_chat_config: KbChatConfig,
        question: str,
    ) -> _SemanticCacheHit | None:
        if not self._semantic_cache_enabled():
            return None
        redis = getattr(self, "_redis", None)
        if redis is None:
            return None
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return None

        threshold = self._semantic_cache_threshold()
        ttl_seconds = self._semantic_cache_ttl_seconds()
        try:
            kb_version = await self._semantic_kb_version(session)
        except Exception:
            kb_version = "kb_unknown"
        cache_key = self._semantic_cache_key(
            session,
            config_fingerprint=self._semantic_config_fingerprint(kb_chat_config),
            kb_version=kb_version,
        )
        try:
            cached_raw = await redis.get(cache_key)
        except Exception:
            return None
        if not isinstance(cached_raw, str) or not cached_raw:
            return None

        try:
            payload = json.loads(cached_raw)
        except Exception:
            return None
        if not isinstance(payload, list) or not payload:
            return None

        try:
            query_embeddings = await self._embedding.embed(
                texts=[normalized_question],
                stage="semantic_cache_lookup",
            )
        except Exception:
            return None
        if not isinstance(query_embeddings, list) or not query_embeddings:
            return None
        query_vector = self._as_float_vector(query_embeddings[0])
        if query_vector is None:
            return None

        best_entry: dict[str, Any] | None = None
        best_score = -1.0
        for item in payload:
            if not isinstance(item, dict):
                continue
            vector = self._as_float_vector(item.get("embedding"))
            if vector is None:
                continue
            score = self._cosine_similarity(query_vector, vector)
            if score > best_score:
                best_score = score
                best_entry = item

        if best_entry is None or best_score < threshold:
            return None

        try:
            ttl_value = int(await redis.ttl(cache_key))
        except Exception:
            ttl_value = ttl_seconds
        if ttl_value <= 0:
            ttl_value = ttl_seconds

        answer = str(best_entry.get("answer") or "").strip()
        if not answer:
            return None
        evidence = best_entry.get("evidence")
        stage_summaries = best_entry.get("stage_summaries")
        metrics = best_entry.get("metrics")
        confidence_level = best_entry.get("confidence_level")
        confidence_score = best_entry.get("confidence_score")
        return _SemanticCacheHit(
            answer=answer,
            evidence=evidence if isinstance(evidence, list) else [],
            confidence_score=(
                float(confidence_score)
                if isinstance(confidence_score, (int, float))
                else None
            ),
            confidence_level=(
                confidence_level
                if isinstance(confidence_level, str)
                and confidence_level in {"high", "medium", "low"}
                else None
            ),
            stage_summaries=stage_summaries if isinstance(stage_summaries, dict) else {},
            metrics=metrics if isinstance(metrics, dict) else {},
            score=max(0.0, min(1.0, float(best_score))),
            threshold=threshold,
            ttl_seconds=ttl_value,
        )

    async def _write_semantic_cache_entry(
        self,
        *,
        session: ChatSession,
        kb_chat_config: KbChatConfig,
        question: str,
        answer: str,
        evidence: list[EvidenceItem],
        confidence_score: float | None,
        confidence_level: str | None,
        stage_summaries: dict[str, Any],
        metrics: dict[str, Any],
    ) -> None:
        if not self._semantic_cache_enabled():
            return
        redis = getattr(self, "_redis", None)
        if redis is None:
            return
        normalized_question = str(question or "").strip()
        normalized_answer = str(answer or "").strip()
        if not normalized_question or not normalized_answer:
            return

        try:
            embeddings = await self._embedding.embed(
                texts=[normalized_question],
                stage="semantic_cache_write",
            )
        except Exception:
            return
        if not isinstance(embeddings, list) or not embeddings:
            return
        vector = self._as_float_vector(embeddings[0])
        if vector is None:
            return

        try:
            kb_version = await self._semantic_kb_version(session)
        except Exception:
            kb_version = "kb_unknown"
        cache_key = self._semantic_cache_key(
            session,
            config_fingerprint=self._semantic_config_fingerprint(kb_chat_config),
            kb_version=kb_version,
        )
        existing: list[dict[str, Any]] = []
        try:
            existing_raw = await redis.get(cache_key)
            if isinstance(existing_raw, str) and existing_raw:
                parsed = json.loads(existing_raw)
                if isinstance(parsed, list):
                    existing = [item for item in parsed if isinstance(item, dict)]
        except Exception:
            existing = []

        question_key = normalized_question.casefold()
        deduped = [
            item
            for item in existing
            if str(item.get("question") or "").strip().casefold() != question_key
        ]
        entry = {
            "question": normalized_question,
            "answer": normalized_answer,
            "embedding": vector,
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "confidence_score": confidence_score,
            "confidence_level": confidence_level,
            "stage_summaries": stage_summaries if isinstance(stage_summaries, dict) else {},
            "metrics": metrics if isinstance(metrics, dict) else {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = [entry, *deduped][: self._semantic_cache_max_items()]
        try:
            await redis.set(
                cache_key,
                json.dumps(payload, ensure_ascii=False),
                ex=self._semantic_cache_ttl_seconds(),
            )
        except Exception:
            return

    @staticmethod
    def _release_retrieval_buffer(exec_ctx: _KbChatExecution) -> None:
        buffer = getattr(exec_ctx, "retrieval_buffer", None)
        if isinstance(buffer, _KbRetrievalBuffer):
            buffer.release()
            return
        fallback_results = getattr(exec_ctx, "retrieval_results", None)
        if isinstance(fallback_results, list):
            fallback_results.clear()
        fallback_evidence = getattr(exec_ctx, "evidence_draft_items_by_round", None)
        if isinstance(fallback_evidence, dict):
            fallback_evidence.clear()
        fallback_meta = getattr(exec_ctx, "retrieval_meta", None)
        if isinstance(fallback_meta, dict):
            fallback_meta.clear()

    @staticmethod
    def _build_terminal_event_payload(
        *,
        status: str,
        run_payload: dict[str, Any],
        assistant_message: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        confidence_score: float | None = None,
        confidence_level: str | None = None,
        stage_summaries: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        message: str | None = None,
        pending_clarification: dict[str, Any] | None = None,
        source: str = "live",
        cache: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "assistant_message": assistant_message,
            "evidence": evidence or [],
            "confidence_score": confidence_score,
            "confidence_level": confidence_level,
            "source": source,
            "cache": cache,
            "stage_summaries": stage_summaries,
            "metrics": metrics,
            "run": run_payload,
        }
        if message is not None:
            payload["message"] = message
        if pending_clarification is not None:
            payload["pending_clarification"] = pending_clarification
        return payload

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
                normalized_metadata = dict(metadata)
                label = metadata.get("label")
                phase = metadata.get("phase")
                order = metadata.get("order")
                nodes.append(
                    {
                        "id": node_id,
                        "label": label if isinstance(label, str) and label.strip() else node_id,
                        "phase": phase if isinstance(phase, str) else None,
                        "order": order if isinstance(order, int) else None,
                        "metadata": normalized_metadata,
                    }
                )

        nodes.sort(key=lambda node: (_node_order(node), str(node.get("id") or "")))

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
                edge["source"],
                edge["target"],
                edge["conditional"],
            )
        )

        hash_source = {
            "version": "1.1",
            "nodes": nodes,
            "edges": edges,
        }
        payload_hash = hashlib.sha256(
            json.dumps(hash_source, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()

        return {"version": "1.1", "hash": payload_hash, "nodes": nodes, "edges": edges}

    @staticmethod
    def _build_drawable_graph_from_builder(graph: object) -> dict[str, Any]:
        builder = getattr(graph, "_graph_builder", None)
        if builder is None:
            raise RuntimeError("KB Chat graph builder is unavailable")

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        seen_edges: set[tuple[str, str, bool]] = set()
        seen_builders: set[int] = set()

        def append_edge(source: Any, target: Any, *, conditional: bool) -> None:
            if not isinstance(source, str) or not isinstance(target, str):
                return
            if source in {"__start__", "__end__"} or target in {"__start__", "__end__"}:
                return
            identity = (source, target, conditional)
            if identity in seen_edges:
                return
            seen_edges.add(identity)
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "conditional": conditional,
                }
            )

        def collect_from_builder(current_builder: object) -> None:
            builder_id = id(current_builder)
            if builder_id in seen_builders:
                return
            seen_builders.add(builder_id)

            for node_id, node_spec in getattr(current_builder, "nodes", {}).items():
                if not isinstance(node_id, str) or node_id in {"__start__", "__end__"}:
                    continue
                if node_id not in seen_nodes:
                    metadata = getattr(node_spec, "metadata", None)
                    nodes.append(
                        {
                            "id": node_id,
                            "metadata": metadata if isinstance(metadata, dict) else {},
                        }
                    )
                    seen_nodes.add(node_id)

            for source, target in getattr(current_builder, "edges", set()):
                append_edge(source, target, conditional=False)

            for source, branch_map in getattr(current_builder, "branches", {}).items():
                if not isinstance(branch_map, dict):
                    continue
                for branch_spec in branch_map.values():
                    ends = getattr(branch_spec, "ends", None)
                    if isinstance(ends, dict):
                        for target in ends.values():
                            append_edge(source, target, conditional=True)

            for node_spec in getattr(current_builder, "nodes", {}).values():
                runnable = getattr(node_spec, "runnable", None)
                nested_builder = getattr(runnable, "builder", None)
                if nested_builder is not None:
                    collect_from_builder(nested_builder)

        collect_from_builder(builder)
        nodes.sort(
            key=lambda node: (
                int(node.get("metadata", {}).get("order"))
                if isinstance(node.get("metadata"), dict)
                and isinstance(node["metadata"].get("order"), int)
                else 10_000,
                str(node.get("id") or ""),
            )
        )
        node_order_index = {
            str(node.get("id")): index for index, node in enumerate(nodes) if isinstance(node.get("id"), str)
        }
        edges.sort(
            key=lambda edge: (
                node_order_index.get(edge["source"], 10_000),
                node_order_index.get(edge["target"], 10_000),
                edge["source"],
                edge["target"],
                edge["conditional"],
            )
        )
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _build_schema_drawable_graph(graph: object) -> dict[str, Any]:
        builder_graph: dict[str, Any] | None = None
        compiled_graph: dict[str, Any] | None = None
        builder_error: Exception | None = None

        try:
            builder_graph = KbChatService._build_drawable_graph_from_builder(graph)
        except Exception as exc:  # pragma: no cover - best effort fallback path
            builder_error = exc

        try:
            compiled_graph = graph.compile().get_graph().to_json()
        except TypeError as exc:
            logger.warning(
                "LangGraph drawable export failed; fallback to builder topology: %s", exc
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning(
                "LangGraph drawable export errored; fallback to builder topology: %s", exc
            )

        if builder_graph and compiled_graph:
            builder_node_count = len(builder_graph.get("nodes", []))
            compiled_node_count = len(compiled_graph.get("nodes", []))
            if builder_node_count > compiled_node_count:
                logger.warning(
                    "LangGraph drawable export is truncated for KB Chat schema; using builder topology instead (builder=%s compiled=%s)",
                    builder_node_count,
                    compiled_node_count,
                )
                return builder_graph
            return compiled_graph

        if builder_graph is not None:
            return builder_graph
        if compiled_graph is not None:
            return compiled_graph
        if builder_error is not None:
            raise builder_error
        raise RuntimeError("Unable to build KB Chat drawable graph schema")

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
        chat_model = create_chat_model(
            settings=self._settings,
            use_previous_response_id=False,
        )
        graph = self._build_graph(
            chat_model=chat_model,
            tools=tools,
            tool_meta_by_name=tool_meta_by_name,
            kb_chat_config=config,
        )
        drawable_graph = self._build_schema_drawable_graph(graph)
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
                "entity_expand_max_candidates": int(
                    kb_chat_config.entity_expand_max_candidates
                ),
                "entity_expand_max_variants": int(
                    kb_chat_config.entity_expand_max_variants
                ),
                "entity_expand_min_confidence": float(
                    kb_chat_config.entity_expand_min_confidence
                ),
                "complexity_cache_enabled": bool(
                    self._settings.kb_chat_complexity_cache_enabled
                ),
                "complexity_cache_ttl_seconds": int(
                    self._settings.kb_chat_complexity_cache_ttl_seconds
                ),
                "retrieval_top_k": int(kb_chat_config.retrieval_top_k),
                "retrieval_rerank_top_k": int(kb_chat_config.retrieval_rerank_top_k),
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
            "hybrid_hits": layer_stats.get("hybrid_hits"),
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

    @staticmethod
    def _safe_percent(value: float | int | None) -> float | None:
        if value is None:
            return None
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        if normalized < 0:
            return 0.0
        if normalized <= 1.0:
            return round(normalized * 100.0, 4)
        return round(normalized, 4)

    @staticmethod
    def _safe_rate(value: float | int | None) -> float:
        percent = KbChatService._safe_percent(value)
        return 100.0 if percent is None else percent

    @staticmethod
    def _extract_run_latency_ms(metrics: dict[str, Any]) -> int | None:
        value = metrics.get("latency_ms")
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
        return None

    @staticmethod
    def _calc_percentile(values: list[int], p: float) -> float:
        ordered = sorted(v for v in values if isinstance(v, int) and v >= 0)
        if not ordered:
            return 0.0
        if len(ordered) == 1:
            return float(ordered[0])
        rank = max(0.0, min(1.0, p)) * (len(ordered) - 1)
        low = math.floor(rank)
        high = math.ceil(rank)
        if low == high:
            return float(ordered[low])
        weight = rank - low
        return float(ordered[low] * (1 - weight) + ordered[high] * weight)

    async def _compute_p95_latency_increase_pct(
        self,
        *,
        current_latency_ms: int,
    ) -> float:
        window_size = int(getattr(self._settings, "kb_chat_gray_release_window_size", 200))
        stmt = (
            select(AgentRun.metrics)
            .where(
                AgentRun.run_type == AgentRunType.KB_ANSWER,
                AgentRun.status == AgentRunStatus.SUCCEEDED,
            )
            .order_by(AgentRun.finished_at.desc())
            .limit(window_size)
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        latencies: list[int] = []
        for raw_metrics in rows:
            metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
            latency_ms = self._extract_run_latency_ms(metrics)
            if latency_ms is None:
                continue
            latencies.append(latency_ms)
        latencies.append(int(current_latency_ms))
        if len(latencies) < 2:
            return 0.0
        baseline = latencies[:-1]
        current_window = latencies
        p95_baseline = self._calc_percentile(baseline, 0.95)
        p95_current = self._calc_percentile(current_window, 0.95)
        if p95_baseline <= 0:
            return 0.0
        return round(((p95_current - p95_baseline) / p95_baseline) * 100.0, 4)

    @staticmethod
    def _compute_route_consistency(
        *,
        query_strategy: str | None,
        routing_decisions: dict[str, Any] | None,
    ) -> float:
        checks: list[bool] = []
        if isinstance(query_strategy, str) and query_strategy:
            checks.append(query_strategy in {"direct", "decomposition", "multi_query"})
        routing = routing_decisions if isinstance(routing_decisions, dict) else {}
        doc_gate_route = (
            routing.get("doc_gate") if isinstance(routing.get("doc_gate"), dict) else {}
        )
        if doc_gate_route:
            doc_gate_next = str(doc_gate_route.get("next_node") or "")
            checks.append(
                doc_gate_next in {"answer_subgraph", "transform_query", "force_exit"}
            )
        answer_subgraph = (
            routing.get("answer_subgraph")
            if isinstance(routing.get("answer_subgraph"), dict)
            else {}
        )
        if answer_subgraph:
            checks.append(
                str(answer_subgraph.get("next_node") or "")
                in {"confidence_calibrate", "transform_query", "force_exit"}
            )
        if not checks:
            return 100.0
        return round((sum(1 for ok in checks if ok) / len(checks)) * 100.0, 4)

    @staticmethod
    def _compute_final_state_consistency(
        *,
        routing_decisions: dict[str, Any] | None,
        terminal_reason: str | None,
    ) -> float:
        routing = routing_decisions if isinstance(routing_decisions, dict) else {}
        answer_subgraph = (
            routing.get("answer_subgraph")
            if isinstance(routing.get("answer_subgraph"), dict)
            else {}
        )
        terminal_phase, terminal_route = resolve_terminal_routing_decision(
            {"routing_decisions": routing},
            next_nodes={"force_exit"},
        )
        next_step = str(answer_subgraph.get("next_node") or "")
        has_force_exit = isinstance(terminal_reason, str) and bool(terminal_reason.strip())
        if not next_step and not has_force_exit:
            return 100.0
        if next_step == "confidence_calibrate":
            return 100.0 if not has_force_exit else 0.0
        if next_step in {"transform_query", "force_exit"}:
            return 100.0 if has_force_exit else 0.0
        if terminal_phase in {"doc_gate", "preprocess"} and terminal_route:
            return 100.0 if has_force_exit else 0.0
        return 0.0

    @staticmethod
    def _compute_clarification_consistency(
        *,
        metrics: dict[str, Any] | None,
        clarification_payload: dict[str, Any] | None,
        terminal_reason: str | None,
    ) -> float:
        metric_values = metrics if isinstance(metrics, dict) else {}
        if metric_values.get("clarification_pending") is not True:
            return 100.0
        is_clarify = str(terminal_reason or "").strip().lower() == "clarify"
        has_payload = isinstance(clarification_payload, dict)
        return 100.0 if is_clarify and has_payload else 0.0

    @staticmethod
    def _build_gray_release_gate(metrics: dict[str, Any]) -> dict[str, Any]:
        route = KbChatService._safe_rate(metrics.get("route_consistency_rate"))
        final = KbChatService._safe_rate(metrics.get("final_state_consistency_rate"))
        clarification = KbChatService._safe_rate(metrics.get("clarification_consistency_rate"))
        p95_increase = float(metrics.get("p95_latency_increase_pct") or 0.0)
        drift_rate = float(metrics.get("protocol_required_field_drift_rate") or 0.0)
        violations: list[str] = []
        if route < _GRAY_ROUTE_THRESHOLD:
            violations.append("route_consistency_rate")
        if final < _GRAY_FINAL_THRESHOLD:
            violations.append("final_state_consistency_rate")
        if clarification < _GRAY_CLARIFICATION_THRESHOLD:
            violations.append("clarification_consistency_rate")
        if p95_increase > _GRAY_P95_THRESHOLD:
            violations.append("p95_latency_increase_pct")
        if drift_rate > 0.0:
            violations.append("protocol_required_field_drift_rate")
        return {
            "pass": len(violations) == 0,
            "violations": violations,
            "thresholds": {
                "route_consistency_rate": _GRAY_ROUTE_THRESHOLD,
                "final_state_consistency_rate": _GRAY_FINAL_THRESHOLD,
                "clarification_consistency_rate": _GRAY_CLARIFICATION_THRESHOLD,
                "p95_latency_increase_pct": _GRAY_P95_THRESHOLD,
                "protocol_required_field_drift_rate": 0.0,
            },
        }

    async def _refresh_semantic_cache_hit_metrics(
        self,
        *,
        stage_summaries: dict[str, Any] | None,
        metrics: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        refreshed_stage_summaries = (
            dict(stage_summaries) if isinstance(stage_summaries, dict) else {}
        )
        metric_values = dict(metrics) if isinstance(metrics, dict) else {}
        route_consistency_rate = self._safe_rate(
            metric_values.get("route_consistency_rate")
        ) or 100.0
        final_state_consistency_rate = 100.0
        clarification_consistency_rate = self._compute_clarification_consistency(
            metrics=metric_values,
            clarification_payload=None,
            terminal_reason=None,
        )
        protocol_required_field_drift_rate = float(
            metric_values.get("protocol_required_field_drift_rate") or 0.0
        )
        p95_latency_increase_pct = await self._compute_p95_latency_increase_pct(
            current_latency_ms=0,
        )
        refreshed_metrics = {
            **metric_values,
            "route_consistency_rate": route_consistency_rate,
            "final_state_consistency_rate": final_state_consistency_rate,
            "clarification_consistency_rate": clarification_consistency_rate,
            "p95_latency_increase_pct": p95_latency_increase_pct,
            "protocol_required_field_drift_rate": protocol_required_field_drift_rate,
            "gray_release_indicators": {
                "route_consistency_rate": route_consistency_rate,
                "final_state_consistency_rate": final_state_consistency_rate,
                "clarification_consistency_rate": clarification_consistency_rate,
                "p95_latency_increase_pct": p95_latency_increase_pct,
                "protocol_required_field_drift_rate": protocol_required_field_drift_rate,
            },
        }
        gray_release_gate = self._build_gray_release_gate(refreshed_metrics)
        refreshed_metrics["gray_release_gate"] = gray_release_gate
        refreshed_stage_summaries["gray_release_gate"] = gray_release_gate
        return refreshed_stage_summaries, refreshed_metrics

    def _persist_gray_release_anomaly_sample(
        self,
        *,
        run_id: uuid.UUID,
        gate: dict[str, Any],
        metrics: dict[str, Any],
        stage_summaries: dict[str, Any],
    ) -> None:
        if not isinstance(gate, dict) or gate.get("pass") is True:
            return
        base_dir = _gray_release_log_dir()
        day_dir = base_dir / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        sample_path = day_dir / f"{run_id}.json"
        sample = {
            "run_id": str(run_id),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "gate": gate,
            "gray_release_indicators": metrics.get("gray_release_indicators"),
            "stage_summaries": stage_summaries,
        }
        sample_path.write_text(
            json.dumps(sample, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _apply_gray_release_rollback_policy(
        self,
        *,
        kb_chat_config: KbChatConfig,
    ) -> tuple[KbChatConfig, dict[str, Any] | None]:
        return kb_chat_config, None

    @staticmethod
    def _sanitize_checkpoint_messages(
        messages: Any,
    ) -> list[SystemMessage | HumanMessage | AIMessage]:
        if not isinstance(messages, list):
            return []

        sanitized: list[SystemMessage | HumanMessage | AIMessage] = []
        for message in messages:
            content = getattr(message, "content", None)
            if not isinstance(content, str) or not content.strip():
                continue
            if isinstance(message, (SystemMessage, HumanMessage)):
                sanitized.append(message)
                continue
            if not isinstance(message, AIMessage):
                continue
            tool_calls = getattr(message, "tool_calls", None)
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if tool_calls:
                continue
            if isinstance(additional_kwargs, dict) and additional_kwargs.get("tool_calls"):
                continue
            sanitized.append(message)
        return sanitized

    @classmethod
    def _sanitize_checkpoint_state(cls, state: Any) -> _CheckpointRestorePlan:
        if not isinstance(state, dict):
            return _CheckpointRestorePlan(
                messages=[],
                reset_fields=[],
                legacy_fields=[],
                schema_supported=False,
            )

        sanitized_messages = cls._sanitize_checkpoint_messages(state.get("messages"))
        legacy_fields: list[str] = []
        schema_version = state.get("schema_version")
        schema_supported = schema_version == STATE_SCHEMA_V3
        if not schema_supported:
            legacy_fields.append("schema_version")
        raw_messages = state.get("messages")
        if isinstance(raw_messages, list) and len(raw_messages) != len(sanitized_messages):
            legacy_fields.append("messages_filtered")
        reset_fields = sorted(field for field in _KB_CHAT_CHECKPOINT_RESET_FIELDS if field in state)
        return _CheckpointRestorePlan(
            messages=sanitized_messages,
            reset_fields=reset_fields,
            legacy_fields=sorted(set(legacy_fields)),
            schema_supported=schema_supported,
        )

    @staticmethod
    def _build_checkpoint_restore_audit(
        *,
        checkpoint_id: str | None,
        applied: bool,
        reset_fields: list[str],
        legacy_fields: list[str],
        schema_supported: bool,
    ) -> dict[str, Any]:
        return {
            "checkpoint_restore_applied": bool(applied),
            "checkpoint_restore_source_checkpoint_id": checkpoint_id,
            "checkpoint_restore_reset_fields": sorted(set(reset_fields)),
            "checkpoint_restore_legacy_fields": sorted(set(legacy_fields)),
            "checkpoint_restore_schema_supported": bool(schema_supported),
        }

    @staticmethod
    def _resolve_kb_chat_user_id(session: ChatSession) -> str:
        return resolve_kb_chat_store_user_id(
            user_id=getattr(session, "user_id", None),
            thread_id=str(session.id),
        )

    async def _get_running_kb_chat_run(
        self,
        *,
        session_id: uuid.UUID,
        exclude_run_id: uuid.UUID | None = None,
    ) -> AgentRun | None:
        stmt = select(AgentRun).where(
            AgentRun.session_id == session_id,
            AgentRun.run_type == AgentRunType.KB_ANSWER,
            AgentRun.status == AgentRunStatus.RUNNING,
        )
        if exclude_run_id is not None:
            stmt = stmt.where(AgentRun.id != exclude_run_id)
        stmt = stmt.order_by(AgentRun.created_at.desc()).limit(1)
        result = await self._db.execute(stmt)
        return result.scalars().first()

    async def _ensure_no_running_kb_chat_run(self, *, session_id: uuid.UUID) -> None:
        await self._db.execute(
            select(ChatSession.id)
            .where(ChatSession.id == session_id)
            .with_for_update()
        )
        running = await self._get_running_kb_chat_run(session_id=session_id)
        if running is None:
            return
        raise AppError(
            code="CHAT_RUN_CONFLICT",
            message="当前会话已有运行中的知识库问答任务，请先完成澄清或等待结束",
            status_code=409,
            details={"run_id": str(running.id)},
        )

    async def _ensure_kb_chat_resume_target_valid(
        self,
        *,
        session: ChatSession,
        run: AgentRun,
    ) -> None:
        await self._db.execute(
            select(ChatSession.id)
            .where(ChatSession.id == session.id)
            .with_for_update()
        )
        running = await self._get_running_kb_chat_run(session_id=session.id)
        if running is None:
            raise AppError(
                code="CHAT_RUN_NOT_RUNNING",
                message="运行记录已完成或已失败",
                status_code=400,
            )
        if running.id != run.id:
            raise AppError(
                code="CHAT_RUN_CONFLICT",
                message="当前会话已有其他运行中的知识库问答任务",
                status_code=409,
                details={"run_id": str(running.id)},
            )

    async def _prepare_kb_chat_execution(
        self,
        *,
        session: ChatSession,
        user_content: str,
        run: AgentRun | None = None,
    ) -> _KbChatExecution:
        resume_requested = run is not None
        started_at = run.started_at if run and run.started_at else datetime.now(timezone.utc)
        thread_id = str(session.id)
        checkpoint_tuple = await CheckpointManager.get_state(thread_id)
        checkpoint_restore = _CheckpointRestorePlan(
            messages=[],
            reset_fields=[],
            legacy_fields=[],
            schema_supported=False,
        )
        checkpoint_id: str | None = None
        if checkpoint_tuple is not None:
            raw_values = (checkpoint_tuple.checkpoint or {}).get(
                "channel_values", {}
            )
            checkpoint_restore = self._sanitize_checkpoint_state(raw_values)
            raw_checkpoint_id = (checkpoint_tuple.checkpoint or {}).get("id")
            checkpoint_id = str(raw_checkpoint_id) if isinstance(raw_checkpoint_id, str) else None

        use_checkpoint_messages = (
            run is not None
            and checkpoint_tuple is not None
            and checkpoint_restore.schema_supported
            and bool(checkpoint_restore.messages)
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
            if checkpoint_tuple is not None and run is None:
                logger.warning(
                    "KB Chat fresh turn ignored checkpoint messages and rebuilt context from DB history",
                    extra={
                        "thread_id": thread_id,
                        "checkpoint_id": checkpoint_id,
                    },
                )
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
        kb_chat_config, rollback_note = await self._apply_gray_release_rollback_policy(
            kb_chat_config=kb_chat_config
        )
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
        retrieval_buffer = _KbRetrievalBuffer(
            results=retrieval_results,
            evidence_by_round=evidence_draft_items_by_round,
            meta=retrieval_meta,
        )

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

        chat_model = create_chat_model(
            settings=self._settings,
            use_previous_response_id=False,
        )

        system_prompt = self._prompts.render_with_few_shot("kb_chat/system")
        context_metrics = self._context_builder.build_metrics(
            history_usage=history_usage,
            history_truncation=history_truncation,
        )
        resolved_user_id = self._resolve_kb_chat_user_id(session)
        reset_fields = list(checkpoint_restore.reset_fields)
        if checkpoint_tuple is not None and not use_checkpoint_messages and checkpoint_restore.messages:
            reset_fields.append("messages")
        checkpoint_restore_audit = self._build_checkpoint_restore_audit(
            checkpoint_id=checkpoint_id,
            applied=use_checkpoint_messages,
            reset_fields=reset_fields,
            legacy_fields=checkpoint_restore.legacy_fields,
            schema_supported=checkpoint_restore.schema_supported,
        )

        messages: list[SystemMessage | HumanMessage | AIMessage] = []
        if use_checkpoint_messages:
            messages.extend(checkpoint_restore.messages)
        else:
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

        runtime_config_payload = kb_chat_config.model_dump(mode="json")
        selected_kb_ids = [str(kid) for kid in (session.selected_kb_ids or [])]
        state = make_initial_state(
            user_input=user_content,
            messages=messages,
        )
        stage_summaries: dict[str, Any] = {}
        if checkpoint_tuple is not None:
            stage_summaries["checkpoint_restore"] = checkpoint_restore_audit
        if isinstance(rollback_note, dict):
            stage_summaries["gray_release_auto_rollback"] = rollback_note
        state["stage_summaries"] = stage_summaries
        state["metrics"] = {
            "context": context_metrics,
            "checkpoint_restore": checkpoint_restore_audit,
        }
        make_run_context = getattr(graph, "make_run_context", None)
        run_context = None
        if callable(make_run_context):
            run_context_kwargs = {
                "thread_id": thread_id,
                "state": state,
                "user_id": resolved_user_id,
                "kb_ids": selected_kb_ids,
                "runtime_config": runtime_config_payload,
            }
            try:
                supported_keys = set(inspect.signature(make_run_context).parameters)
            except (TypeError, ValueError):
                supported_keys = {"thread_id", "state"}
            run_context = make_run_context(
                **{
                    key: value
                    for key, value in run_context_kwargs.items()
                    if key in supported_keys
                }
            )
        try:
            store = StoreManager.get_store()
        except Exception:
            store = None
        compiled_graph = graph.compile(
            checkpointer=CheckpointManager.get_checkpointer(),
            store=store,
        )

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
            retrieval_buffer=retrieval_buffer,
            graph=graph,
            compiled_graph=compiled_graph,
            state=state,
            run_context=run_context,
            resume_checkpoint_id=(
                str(run.id)
                if resume_requested and getattr(run, "id", None) is not None
                else None
            ),
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
        stage_attempts: dict[str, int] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        metrics = base_metrics if isinstance(base_metrics, dict) else {}
        retry_cache_metrics = self._build_retry_cache_metrics(stage_attempts)
        context_metrics = self._context_builder.build_metrics(
            history_usage=history_usage,
            history_truncation=history_truncation,
            retrieval_usage=retrieval_meta.get("usage"),
            retrieval_truncation=retrieval_meta.get("truncation"),
        )
        metrics = {
            **metrics,
            **retry_cache_metrics,
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
            "retry_cache": retry_cache_metrics,
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

        gray_release_indicators = {
            "route_consistency_rate": metrics.get("route_consistency_rate"),
            "final_state_consistency_rate": metrics.get("final_state_consistency_rate"),
            "clarification_consistency_rate": metrics.get("clarification_consistency_rate"),
            "p95_latency_increase_pct": metrics.get("p95_latency_increase_pct"),
            "protocol_required_field_drift_rate": metrics.get(
                "protocol_required_field_drift_rate"
            ),
        }
        metrics = {**metrics, "gray_release_indicators": gray_release_indicators}
        stage_summaries = {
            **stage_summaries,
            "gray_release_indicators": gray_release_indicators,
        }

        metrics = ensure_json_safe(metrics, settings=self._settings, label="metrics")
        stage_summaries = ensure_json_safe(
            stage_summaries, settings=self._settings, label="stage_summaries"
        )
        return metrics, stage_summaries

    @staticmethod
    def _build_retry_cache_metrics(
        stage_attempts: dict[str, int] | None,
    ) -> dict[str, Any]:
        retry_node_breakdown: dict[str, int] = {}
        retry_attempts_total = 0
        if isinstance(stage_attempts, dict):
            for node_name, raw_attempts in stage_attempts.items():
                if not isinstance(node_name, str) or not node_name:
                    continue
                if not isinstance(raw_attempts, int):
                    continue
                retry_count = max(raw_attempts - 1, 0)
                if retry_count <= 0:
                    continue
                retry_node_breakdown[node_name] = retry_count
                retry_attempts_total += retry_count

        return {
            "retry_attempts_total": retry_attempts_total,
            "retry_node_breakdown": retry_node_breakdown,
            "graph_cache_hit_total": 0,
            "graph_cache_miss_total": 0,
            "cache_disabled_reason": "compile_cache_disabled",
        }

    @staticmethod
    def _build_protocol_metrics(
        *,
        protocol_emit_total: int,
        protocol_required_field_drift_count: int,
        protocol_salvage_count: int,
        node_io_snapshot_truncated_count: int,
        custom_event_unhandled_count: int,
        heartbeat_stats: SseHeartbeatStats | None = None,
    ) -> dict[str, Any]:
        emit_total = max(0, int(protocol_emit_total))
        drift_count = max(0, int(protocol_required_field_drift_count))
        salvage_count = max(0, int(protocol_salvage_count))
        truncated_count = max(0, int(node_io_snapshot_truncated_count))
        custom_unhandled = max(0, int(custom_event_unhandled_count))
        heartbeat_sent_count = (
            heartbeat_stats.sent_count if isinstance(heartbeat_stats, SseHeartbeatStats) else 0
        )
        heartbeat_gaps = (
            heartbeat_stats.gap_ms_samples
            if isinstance(heartbeat_stats, SseHeartbeatStats)
            else []
        )
        heartbeat_gap_ms_p95 = round(
            KbChatService._calc_percentile(heartbeat_gaps, 0.95),
            4,
        )
        protocol_drift_rate = round((drift_count / emit_total) * 100.0, 4) if emit_total > 0 else 0.0
        return {
            "protocol_emit_total": emit_total,
            "protocol_required_field_drift_count": drift_count,
            "protocol_required_field_drift_rate": protocol_drift_rate,
            "protocol_salvage_count": salvage_count,
            "node_io_snapshot_truncated_count": truncated_count,
            "custom_event_unhandled_count": custom_unhandled,
            "sse_heartbeat_sent_count": heartbeat_sent_count,
            "sse_heartbeat_gap_ms_p95": heartbeat_gap_ms_p95,
        }

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

    @staticmethod
    def _resolve_terminal_reason(
        *,
        clarification_payload: dict[str, Any] | None = None,
        routing_decisions: dict[str, Any] | None = None,
        reflection: dict[str, Any] | None = None,
        degrade_reason: str | None = None,
    ) -> str | None:
        if isinstance(clarification_payload, dict):
            return "clarify"
        _, terminal_route = resolve_terminal_routing_decision(
            {"routing_decisions": routing_decisions or {}},
            next_nodes={"force_exit"},
        )
        if terminal_route:
            action = str(terminal_route.get("action") or "").strip().lower()
            if action == "clarify":
                return "clarify"
            reason = str(terminal_route.get("reason") or "").strip().lower()
            if reason and reason not in {"passed", "none"}:
                return reason
            if str(terminal_route.get("next_node") or "").strip().lower() == "force_exit":
                return "force_exit"
        if isinstance(degrade_reason, str) and degrade_reason.strip():
            return degrade_reason.strip().lower()
        if isinstance(reflection, dict):
            action = str(reflection.get("action") or "").strip().lower()
            if action == "clarify":
                return "clarify"
            if action not in {"force_exit", "transform_query"}:
                return None
            reason = str(reflection.get("reason") or "").strip().lower()
            if reason and reason not in {"passed", "none"}:
                return reason
            if action == "force_exit":
                return "force_exit"
        return None

    @classmethod
    def _extract_clarification_pending(
        cls,
        *,
        clarification_payload: dict[str, Any] | None,
        answer: str,
        reflection: dict[str, Any] | None = None,
    ) -> tuple[str | None, PendingClarification | None]:
        reason = cls._resolve_terminal_reason(
            clarification_payload=clarification_payload,
            reflection=reflection,
        )
        if reason != "clarify":
            return None, None

        pending_clarification = cls._coerce_pending_clarification(clarification_payload)

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
        answer: str,
        clarification_payload: dict[str, Any] | None = None,
        routing_decisions: dict[str, Any] | None = None,
        reflection: dict[str, Any] | None = None,
        best_answer: str | None = None,
    ) -> tuple[AgentRunStatus, str | None]:
        """Resolve terminal run status from canonical state + final answer."""
        reason = KbChatService._resolve_terminal_reason(
            clarification_payload=clarification_payload,
            routing_decisions=routing_decisions,
            reflection=reflection,
        )
        if reason == "clarify":
            return AgentRunStatus.SUCCEEDED, None

        _, terminal_route = resolve_terminal_routing_decision(
            {"routing_decisions": routing_decisions or {}},
            next_nodes={"force_exit"},
        )
        terminal_force_exit = bool(terminal_route)
        review_passed = (
            reflection.get("review_passed")
            if isinstance(reflection, dict) and not terminal_force_exit
            else False if terminal_force_exit else None
        )
        answer_text = extract_answer_text(answer).strip()
        canonical_best_answer = extract_answer_text(best_answer).strip() if best_answer else ""
        best_answer_matches = (
            not terminal_force_exit
            and bool(canonical_best_answer)
            and answer_text == canonical_best_answer
        )
        if (
            (review_passed is True or best_answer_matches)
            and answer_text
            and "无法回答" not in answer_text
        ):
            return AgentRunStatus.SUCCEEDED, None

        if not reason:
            return AgentRunStatus.SUCCEEDED, None

        if answer_text and is_kb_refusal_answer(answer_text):
            return AgentRunStatus.FAILED, answer_text

        message = resolve_kb_refusal_answer(reason=reason)
        return AgentRunStatus.FAILED, message

    @staticmethod
    def _build_no_evidence_response(
        *,
        reason_code: str | None,
        stage_summaries: dict[str, Any],
        selected_kb_ids: list[uuid.UUID] | None,
    ) -> str:
        normalized_reason_code = str(reason_code or "").strip().lower()

        reason_text_map = {
            "clarify": "当前问题信息不足，需要先补充关键条件",
            "max_total_rounds": "多轮检索与校验后仍无可用证据",
            "max_retrieval_retries": "多次重写检索后仍未命中相关证据",
            "max_generation_retries": "多次生成与校验后仍无法得到可引用答案",
            "fallback_closed": "评估器触发保守策略，未通过证据校验",
            "severe_conflict": "检索证据出现明显冲突，无法稳定作答",
            "conflict_retry_exhausted": "冲突证据重试后仍未收敛",
        }
        reason_text = reason_text_map.get(
            normalized_reason_code, "未检索到可用于回答的证据片段"
        )

        stage_label_map = {
            "merge_context": "上下文合并",
            "coref_rewrite": "指代消解",
            "ambiguity_check": "歧义检测",
            "normalize_rewrite": "问题规范化",
            "complexity_classify": "复杂度分类",
            "decomposition": "问题拆解",
            "generate_variants": "多路查询扩展",
            "entity_expand": "实体扩展",
            "hyde": "假设文档扩展",
            "prepare_messages": "检索准备",
            "retrieval": "检索融合",
            "doc_gate_route": "相关性评估",
            "answer_subgraph": "答案子图",
            "generator": "答案生成",
            "answer_review": "答案审查",
            "answer_repair": "答案修复",
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
        if normalized_reason_code == "clarify":
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
    def _semantic_cache_skip_reason(
        *,
        clarification_payload: dict[str, Any] | None,
        routing_decisions: dict[str, Any] | None,
        reflection: dict[str, Any] | None,
        degrade_reason: str | None,
        answer: str,
    ) -> str | None:
        reason = KbChatService._resolve_terminal_reason(
            clarification_payload=clarification_payload,
            routing_decisions=routing_decisions,
            reflection=reflection,
            degrade_reason=degrade_reason,
        )
        if reason in {"clarify", "severe_conflict", "conflict_retry_exhausted"}:
            return reason
        if is_kb_refusal_answer(extract_answer_text(answer)):
            return "refusal_answer"
        return None

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
                "draft_generate": "generator",
                "answer_subgraph": "answer_subgraph",
                "answer_review_citation": "answer_review",
                "answer_review_factual": "answer_review",
                "answer_review_answerability": "answer_review",
                "answer_review_fuse": "answer_review",
            }.get(node, node)
            candidate = stage_summaries.get(summary_key)
            if isinstance(candidate, dict):
                node_summary = candidate

        io_summary: dict[str, Any] = {}
        if isinstance(node_summary, dict):
            for key in (
                "rewritten",
                "reason",
                "strategy",
                "candidate_count",
                "selected_candidate_id",
                "selected_query",
                "branch_count",
                "best_retrieval_count",
                "normalization_source",
                "count",
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
                "review_confidence",
                "review_risk_level",
                "review_decision_source",
                "review_breakdown",
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

        if node == "prepare_messages" and isinstance(node_summary, dict):
            message_plan = (
                node_summary.get("message_plan")
                if isinstance(node_summary.get("message_plan"), dict)
                else {}
            )
            query_bundle = (
                node_summary.get("query_bundle")
                if isinstance(node_summary.get("query_bundle"), dict)
                else {}
            )
            diagnostics = (
                node_summary.get("diagnostics")
                if isinstance(node_summary.get("diagnostics"), dict)
                else {}
            )
            budget = (
                message_plan.get("budget")
                if isinstance(message_plan.get("budget"), dict)
                else {}
            )
            for key, value in (
                ("message_plan_strategy", message_plan.get("strategy")),
                ("message_plan_candidate_count", message_plan.get("candidate_count")),
                ("message_plan_selected_count", message_plan.get("selected_count")),
                ("message_plan_dropped_count", message_plan.get("dropped_count")),
                ("message_plan_max_candidates", budget.get("max_candidates")),
                ("message_plan_min_queries", budget.get("min_queries")),
                ("query_bundle_items_count", query_bundle.get("items_count")),
                ("query_bundle_kind_breakdown", query_bundle.get("kind_breakdown")),
                ("query_bundle_dedup_stats", query_bundle.get("dedup_stats")),
                ("fallback_reason", diagnostics.get("fallback_reason")),
                ("quality_signals", diagnostics.get("quality_signals")),
            ):
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
                io_summary["query_bundle_items_count"] = len(query_items)
                io_summary["query_count"] = len(query_items)

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

        if node == "draft_generate":
            draft_answer = update.get("draft_answer")
            if isinstance(draft_answer, str) and draft_answer.strip():
                io_summary["draft_preview"] = KbChatService._shorten_stream_text(
                    draft_answer, 180
                )

        if node in {"ambiguity_check", "answer_subgraph", "force_exit"}:
            final_answer = update.get("final_answer")
            if isinstance(final_answer, str) and final_answer.strip():
                io_summary["final_preview"] = KbChatService._shorten_stream_text(
                    final_answer, 180
                )

        if node == "answer_review_fuse":
            best_answer = update.get("best_answer")
            if isinstance(best_answer, str) and best_answer.strip():
                io_summary["best_answer_preview"] = KbChatService._shorten_stream_text(
                    best_answer, 120
                )

        if node == "answer_subgraph":
            answer_summary = node_summary if isinstance(node_summary, dict) else {}
            routing = (
                update.get("routing_decisions")
                if isinstance(update.get("routing_decisions"), dict)
                else {}
            )
            answer_route = (
                routing.get("answer_subgraph")
                if isinstance(routing.get("answer_subgraph"), dict)
                else {}
            )
            next_node = answer_route.get("next_node")
            reason = answer_route.get("reason") or answer_summary.get("reason")
            if isinstance(next_node, str) and next_node:
                io_summary["next_node"] = next_node
            if isinstance(reason, str) and reason:
                io_summary["reason"] = reason
            degrade_reason = update.get("degrade_reason")
            if isinstance(degrade_reason, str) and degrade_reason.strip():
                io_summary["degrade_reason"] = degrade_reason.strip()

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
        current_step_status_override: str | None = None,
    ) -> dict[str, Any]:
        current_step_status = (
            current_step_status_override
            if isinstance(current_step_status_override, str)
            and current_step_status_override
            else stage_status.get(current_step_id) if current_step_id else None
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
        event_id: str | None = None,
        seq: int | None = None,
        attempt: int | None = None,
        node_path: list[str] | None = None,
    ) -> dict[str, Any]:
        ts = payload.get("ts")
        if not isinstance(ts, str) or not ts:
            ts = datetime.now(timezone.utc).isoformat()
        envelope: dict[str, Any] = {
            "type": event_type,
            "version": _STREAM_EVENT_VERSION,
            "event_id": event_id or f"{run_id}:{seq if isinstance(seq, int) else 0}",
            "seq": int(seq or 0),
            "ts": ts,
            "run": {"id": str(run_id)},
            "attempt": attempt,
            "node_path": node_path or [],
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
        merged = {**payload, **envelope}
        validate_event_envelope_v2(merged)
        return merged

    @staticmethod
    def _build_node_io_payload(
        *,
        run_id: uuid.UUID,
        execution_id: str | None = None,
        node_name: str,
        node_id: str,
        phase: str,
        attempt: int | None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        input_snapshot: dict[str, Any] | None = None,
        output_snapshot: dict[str, Any] | None = None,
        display_input_items: list[dict[str, Any]] | None = None,
        display_output_items: list[dict[str, Any]] | None = None,
        error_summary: str | None = None,
        latency_ms: int | None = None,
        ts: datetime | None = None,
        node_path: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": str(run_id),
            "node_name": node_name,
            "node_id": node_id,
            "phase": phase,
            "attempt": attempt,
            "ts": (ts or datetime.now(timezone.utc)).isoformat(),
        }
        if isinstance(execution_id, str) and execution_id:
            payload["execution_id"] = execution_id
            payload["task_id"] = execution_id
        if input_summary is not None:
            payload["input_summary"] = input_summary
        if output_summary is not None:
            payload["output_summary"] = output_summary
        if input_snapshot is not None:
            payload["input_snapshot"] = input_snapshot
        if output_snapshot is not None:
            payload["output_snapshot"] = output_snapshot
        if display_input_items is not None:
            payload["display_input_items"] = display_input_items
        if display_output_items is not None:
            payload["display_output_items"] = display_output_items
        if error_summary is not None:
            payload["error_summary"] = error_summary
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        return KbChatService._build_protocol_event_payload(
            event_type="node_io",
            run_id=run_id,
            payload=payload,
            node={"id": node_id, "name": node_name},
            node_path=node_path,
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
    def _build_graph_stream_options() -> dict[str, Any]:
        return {
            "stream_mode": ["messages", "updates", "custom", "tasks"],
            "subgraphs": True,
            "version": "v2",
        }

    @staticmethod
    def _build_step_payload_from_task_event(
        *,
        payload: dict[str, Any],
        node_path: list[str] | None = None,
    ) -> dict[str, Any] | None:
        task_id = payload.get("id")
        node_name = payload.get("name")
        if (
            not isinstance(task_id, str)
            or not task_id
            or not isinstance(node_name, str)
            or not node_name
        ):
            return None

        normalized_node_path = (
            [str(item) for item in node_path if isinstance(item, str) and item]
            if isinstance(node_path, list)
            else []
        )
        if not normalized_node_path or normalized_node_path[-1] != node_name:
            normalized_node_path = [*normalized_node_path, node_name]
        ts = datetime.now(timezone.utc).isoformat()

        if "input" in payload or "triggers" in payload:
            triggers = payload.get("triggers")
            meta: dict[str, Any] = {
                "task_id": task_id,
                "node_path": normalized_node_path,
            }
            if isinstance(triggers, list):
                meta["triggers"] = [
                    str(item) for item in triggers if isinstance(item, str)
                ]
            return {
                "execution_id": task_id,
                "step_id": node_name,
                "label": node_name,
                "status": "started",
                "node": node_name,
                "ts": ts,
                "meta": meta,
            }

        interrupts = payload.get("interrupts")
        if isinstance(interrupts, list) and interrupts:
            return {
                "execution_id": task_id,
                "step_id": node_name,
                "label": node_name,
                "status": "waiting_user",
                "node": node_name,
                "ts": ts,
                "meta": {
                    "task_id": task_id,
                    "node_path": normalized_node_path,
                    "interrupt_count": len(interrupts),
                },
            }

        error_message = payload.get("error")
        meta = {
            "task_id": task_id,
            "node_path": normalized_node_path,
        }
        result = payload.get("result")
        if isinstance(result, dict) and result:
            meta["result_keys"] = [str(key) for key in result.keys()]
        return {
            "execution_id": task_id,
            "step_id": node_name,
            "label": node_name,
            "status": (
                "failed"
                if isinstance(error_message, str) and error_message
                else "completed"
            ),
            "node": node_name,
            "message": (
                error_message
                if isinstance(error_message, str) and error_message
                else None
            ),
            "ts": ts,
            "meta": meta,
        }

    @staticmethod
    def _normalize_graph_stream_event(
        event: Any,
    ) -> tuple[str, Any, list[str] | None] | None:
        """Normalize LangGraph v2 StreamPart or legacy tuple stream output."""
        def _to_node_path(value: Any) -> list[str] | None:
            if isinstance(value, tuple):
                path = [str(item) for item in value if isinstance(item, str) and item]
                return path or None
            if isinstance(value, list):
                path = [str(item) for item in value if isinstance(item, str) and item]
                return path or None
            return None

        if isinstance(event, dict):
            mode = event.get("type")
            if not isinstance(mode, str):
                return None
            return mode, event.get("data"), _to_node_path(event.get("ns"))
        if isinstance(event, tuple):
            if len(event) == 2:
                mode, chunk = event
                node_path = None
            elif len(event) == 3:
                node_path = _to_node_path(event[0])
                mode, chunk = event[1], event[2]
            else:
                return None
            return (mode, chunk, node_path) if isinstance(mode, str) else None
        if isinstance(event, list):
            if len(event) == 2:
                mode, chunk = event[0], event[1]
                node_path = None
            elif len(event) == 3:
                node_path = _to_node_path(event[0])
                mode, chunk = event[1], event[2]
            else:
                return None
            return (mode, chunk, node_path) if isinstance(mode, str) else None
        return None

    @staticmethod
    def _normalize_stream_namespace(node_path: list[str] | None) -> tuple[str, ...]:
        if not isinstance(node_path, list):
            return ()
        return tuple(str(item) for item in node_path if isinstance(item, str) and item)

    @staticmethod
    def _build_stream_execution_scope(
        *,
        node_name: str | None,
        node_path: list[str] | None = None,
    ) -> tuple[tuple[str, ...], str] | None:
        if not isinstance(node_name, str) or not node_name:
            return None
        return (KbChatService._normalize_stream_namespace(node_path), node_name)

    @staticmethod
    def _remember_stream_execution(
        *,
        stream_state: _KbChatStreamRunState,
        execution_id: str | None,
        node_name: str | None,
        node_path: list[str] | None = None,
    ) -> None:
        if not isinstance(execution_id, str) or not execution_id:
            return
        scope = KbChatService._build_stream_execution_scope(
            node_name=node_name,
            node_path=node_path,
        )
        if scope is None:
            return
        stream_state.latest_execution_by_scope[scope] = execution_id

    @staticmethod
    def _resolve_stream_execution_id(
        *,
        stream_state: _KbChatStreamRunState,
        payload: dict[str, Any],
        node_name: str | None,
        node_path: list[str] | None = None,
    ) -> str | None:
        execution_id = payload.get("execution_id")
        if isinstance(execution_id, str) and execution_id:
            return execution_id
        task_id = payload.get("task_id")
        if isinstance(task_id, str) and task_id:
            return task_id
        scope = KbChatService._build_stream_execution_scope(
            node_name=node_name,
            node_path=node_path,
        )
        if scope is None:
            return None
        return stream_state.latest_execution_by_scope.get(scope)

    @staticmethod
    def _build_scoped_node_path(
        *,
        node_name: str | None,
        node_path: list[str] | None = None,
    ) -> list[str]:
        scoped_path = list(KbChatService._normalize_stream_namespace(node_path))
        if isinstance(node_name, str) and node_name:
            if not scoped_path or scoped_path[-1] != node_name:
                scoped_path.append(node_name)
        return scoped_path

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
    def _resolve_stream_state_node_name(
        *,
        payload: dict[str, Any],
        node_path: list[str] | None = None,
    ) -> str | None:
        node_name = payload.get("node_name")
        if isinstance(node_name, str) and node_name:
            return node_name
        node = payload.get("node")
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str) and node_id:
                return node_id
            node_name = node.get("name")
            if isinstance(node_name, str) and node_name:
                return node_name
        if isinstance(node_path, list) and node_path:
            candidate = node_path[-1]
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    @staticmethod
    def _apply_stream_state_node_io(
        *,
        stream_state: _KbChatStreamRunState,
        payload: dict[str, Any],
        node_path: list[str] | None = None,
    ) -> str | None:
        node_name = KbChatService._resolve_stream_state_node_name(
            payload=payload,
            node_path=node_path,
        )
        phase = payload.get("phase")
        if node_name is None or phase not in {"start", "end", "error"}:
            return None

        raw_attempt = KbChatService._safe_non_negative_int(payload.get("attempt"))
        attempt = raw_attempt if isinstance(raw_attempt, int) and raw_attempt > 0 else None
        previous_attempt = stream_state.stage_attempts.get(node_name, 0)
        if phase == "start":
            stream_state.stage_attempts[node_name] = (
                attempt if attempt is not None else previous_attempt + 1
            )
            stream_state.stage_status[node_name] = "started"
        elif phase == "end":
            stream_state.stage_attempts[node_name] = (
                attempt if attempt is not None else previous_attempt or 1
            )
            stream_state.stage_status[node_name] = "completed"
        else:
            stream_state.stage_attempts[node_name] = (
                attempt if attempt is not None else previous_attempt or 1
            )
            stream_state.stage_status[node_name] = "failed"

        stream_state.current_step_id = node_name
        stream_state.current_node = node_name
        return node_name

    @staticmethod
    def _apply_stream_state_step(
        *,
        stream_state: _KbChatStreamRunState,
        payload: dict[str, Any],
        node_path: list[str] | None = None,
    ) -> str | None:
        node_name = payload.get("node") or payload.get("step_id")
        status = payload.get("status")
        if not isinstance(node_name, str) or not node_name or not isinstance(status, str):
            return None

        previous_attempt = stream_state.stage_attempts.get(node_name, 0)
        if status == "started":
            stream_state.stage_attempts[node_name] = previous_attempt + 1
            stream_state.stage_status[node_name] = "started"
        elif status == "waiting_user":
            stream_state.stage_attempts[node_name] = previous_attempt or 1
            stream_state.stage_status[node_name] = "waiting_user"
        elif status == "failed":
            stream_state.stage_attempts[node_name] = previous_attempt or 1
            stream_state.stage_status[node_name] = "failed"
        else:
            stream_state.stage_attempts[node_name] = previous_attempt or 1
            stream_state.stage_status[node_name] = "completed"

        stream_state.current_step_id = node_name
        stream_state.current_node = node_name
        KbChatService._remember_stream_execution(
            stream_state=stream_state,
            execution_id=(
                payload.get("execution_id")
                if isinstance(payload.get("execution_id"), str)
                else None
            ),
            node_name=node_name,
            node_path=node_path,
        )
        return node_name

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
        best_answer_meta: dict[str, Any] | None,
        loop_counts: dict[str, Any] | None,
    ) -> int | None:
        if isinstance(best_answer_meta, dict):
            round_value = cls._safe_non_negative_int(best_answer_meta.get("retrieval_round"))
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
        stream_state: StreamState,
    ) -> tuple[str | None, str | None]:
        answer_text = extract_answer_text(answer).strip()
        if answer_text:
            return answer_text, "final_answer"

        final_answer = extract_answer_text(stream_state.final_answer).strip()
        if final_answer:
            return final_answer, "stream_state.final_answer"

        draft_answer = extract_answer_text(stream_state.draft_answer).strip()
        if draft_answer:
            return draft_answer, "stream_state.draft_answer"

        for msg in reversed(stream_state.messages):
            if isinstance(msg, AIMessage):
                text = extract_answer_text(msg.content).strip()
                if text:
                    return text, "ai_message"

        best_answer = stream_state.best_answer
        if isinstance(best_answer, str) and best_answer.strip():
            return best_answer.strip(), "stream_state.best_answer"

        return None, None

    @staticmethod
    def _clarification_round_count(metrics: dict[str, Any] | None) -> int:
        if not isinstance(metrics, dict):
            return 0
        value = metrics.get("clarification_round")
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
            run.metrics if isinstance(run.metrics, dict) else None
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
            stage_summaries=run.stage_summaries if isinstance(run.stage_summaries, dict) else None,
            metrics=run.metrics if isinstance(run.metrics, dict) else None,
            run=AgentRunRead.model_validate(run),
        )

    async def _persist_semantic_cache_hit(
        self,
        *,
        session: ChatSession,
        user_content: str,
        cache_hit: _SemanticCacheHit,
    ) -> ChatAnswerResponse:
        now = datetime.now(timezone.utc)
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=user_content,
        )
        self._db.add(user_msg)
        run = AgentRun(
            id=uuid.uuid4(),
            run_type=AgentRunType.KB_ANSWER,
            session_id=session.id,
            question=user_content,
            selected_kb_ids=session.selected_kb_ids,
            allow_external=session.allow_external,
            mode=session.mode,
            status=AgentRunStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
            final_output=cache_hit.answer,
            error_message=None,
        )
        self._db.add(run)

        evidence_items: list[EvidenceItem] = []
        for raw_item in cache_hit.evidence:
            if not isinstance(raw_item, dict):
                continue
            try:
                evidence_items.append(EvidenceItem.model_validate(raw_item))
            except Exception:
                continue
        persisted_evidence_items: list[EvidenceItem] = []
        seen_evidence_chunk_ids: set[uuid.UUID] = set()
        for item in evidence_items:
            excerpt = str(item.excerpt or "").strip()
            if not excerpt:
                continue
            source_kind = (
                EvidenceSourceKind.KB
                if str(item.source_kind) == EvidenceSourceKind.KB.value
                else EvidenceSourceKind.EXTERNAL
            )
            if (
                source_kind == EvidenceSourceKind.KB
                and (
                    item.kb_id is None
                    or item.material_id is None
                    or item.chunk_id is None
                )
            ):
                continue
            if item.chunk_id is not None and item.chunk_id in seen_evidence_chunk_ids:
                continue
            self._db.add(
                Evidence(
                    run_id=run.id,
                    source_kind=source_kind,
                    kb_id=item.kb_id,
                    material_id=item.material_id,
                    chunk_id=item.chunk_id,
                    locator=item.locator if isinstance(item.locator, dict) else None,
                    excerpt=excerpt[:500],
                )
            )
            persisted_evidence_items.append(item)
            if item.chunk_id is not None:
                seen_evidence_chunk_ids.add(item.chunk_id)

        stage_summaries = {
            **(cache_hit.stage_summaries if isinstance(cache_hit.stage_summaries, dict) else {}),
            "retry_cache": self._build_retry_cache_metrics({}),
            "semantic_cache": {
                "hit": True,
                "score": cache_hit.score,
                "threshold": cache_hit.threshold,
                "ttl_seconds": cache_hit.ttl_seconds,
            },
        }
        metrics = {
            **(cache_hit.metrics if isinstance(cache_hit.metrics, dict) else {}),
            **self._build_retry_cache_metrics({}),
            "semantic_cache": {
                "hit": True,
                "score": cache_hit.score,
                "threshold": cache_hit.threshold,
                "ttl_seconds": cache_hit.ttl_seconds,
            },
            "latency_ms": 0,
        }
        stage_summaries, metrics = await self._refresh_semantic_cache_hit_metrics(
            stage_summaries=stage_summaries,
            metrics=metrics,
        )
        gray_release_gate = (
            metrics.get("gray_release_gate") if isinstance(metrics.get("gray_release_gate"), dict) else {}
        )
        gray_release_gate = {
            **gray_release_gate,
            "source_run_id": str(run.id),
            "evaluated_at": run.finished_at.isoformat(),
            "trigger_rollback": (
                bool(
                    getattr(
                        self._settings,
                        "kb_chat_gray_release_auto_rollback_enabled",
                        True,
                    )
                )
                and gray_release_gate.get("pass") is False
            ),
        }
        metrics["gray_release_gate"] = gray_release_gate
        stage_summaries["gray_release_gate"] = gray_release_gate
        run.stage_summaries = ensure_json_safe(
            stage_summaries,
            settings=self._settings,
            label="stage_summaries",
        )
        run.metrics = ensure_json_safe(metrics, settings=self._settings, label="metrics")

        assistant_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content=cache_hit.answer,
        )
        self._db.add(assistant_msg)
        await self._db.commit()
        await self._db.refresh(assistant_msg)
        await self._db.refresh(run)

        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=persisted_evidence_items,
            confidence_score=cache_hit.confidence_score,
            confidence_level=cast(
                Literal["high", "medium", "low"] | None,
                cache_hit.confidence_level,
            ),
            source="cached",
            cache=SemanticCacheMeta(
                hit=True,
                score=cache_hit.score,
                threshold=cache_hit.threshold,
                ttl_seconds=cache_hit.ttl_seconds,
            ),
            stage_summaries=run.stage_summaries if isinstance(run.stage_summaries, dict) else None,
            metrics=run.metrics if isinstance(run.metrics, dict) else None,
            run=AgentRunRead.model_validate(run),
        )

    async def answer_stream(
        self,
        *,
        session: ChatSession,
        user_content: str,
        request: object | None = None,
        run: AgentRun | None = None,
        sse_heartbeat_stats: SseHeartbeatStats | None = None,
    ) -> Any:
        """处理用户问题并返回流式 SSE（状态与节点事件基于 LangGraph 原生流）。"""
        if run is None:
            await self._ensure_no_running_kb_chat_run(session_id=session.id)
            cache_config = self._resolve_session_kb_chat_config(session)
            cache_hit = await self._semantic_cache_lookup(
                session=session,
                kb_chat_config=cache_config,
                question=user_content,
            )
            if cache_hit is not None:
                cached_response = await self._persist_semantic_cache_hit(
                    session=session,
                    user_content=user_content,
                    cache_hit=cache_hit,
                )
                cached_stage_status: dict[str, str] = {}
                cached_stage_attempts: dict[str, int] = {}
                run_payload = cached_response.run.model_dump(mode="json")
                yield (
                    "meta",
                    self._build_protocol_event_payload(
                        event_type="meta",
                        run_id=cached_response.run.id,
                        payload={
                            "run_id": str(cached_response.run.id),
                            "session_id": str(session.id),
                            "session_type": session.session_type.value,
                            "thread_id": str(session.id),
                            "mode": session.mode.value,
                            "source": "cached",
                        },
                        event_id=f"{cached_response.run.id}:0",
                        seq=0,
                    ),
                )
                yield (
                    "state",
                    self._build_protocol_event_payload(
                        event_type="state",
                        run_id=cached_response.run.id,
                        payload=self._build_stream_state_payload(
                            run_id=cached_response.run.id,
                            run_status=AgentRunStatus.RUNNING.value,
                            current_step_id=None,
                            current_node=None,
                            stage_status=cached_stage_status,
                            stage_attempts=cached_stage_attempts,
                            state_version=1,
                            active_path=self._build_active_path(
                                stage_status=cached_stage_status,
                                current_step_id=None,
                            ),
                            message="知识库问答开始",
                        ),
                        event_id=f"{cached_response.run.id}:1",
                        seq=1,
                    ),
                )
                yield (
                    "stream_end",
                    self._build_protocol_event_payload(
                        event_type="stream_end",
                        run_id=cached_response.run.id,
                        payload={
                            "run_id": str(cached_response.run.id),
                            "source": "cached",
                            "terminal_candidate": "out200",
                            "ts": datetime.now(timezone.utc).isoformat(),
                        },
                        event_id=f"{cached_response.run.id}:2",
                        seq=2,
                    ),
                )
                yield (
                    "state",
                    self._build_protocol_event_payload(
                        event_type="state",
                        run_id=cached_response.run.id,
                        payload=self._build_stream_state_payload(
                            run_id=cached_response.run.id,
                            run_status=AgentRunStatus.SUCCEEDED.value,
                            current_step_id=None,
                            current_node=None,
                            stage_status=cached_stage_status,
                            stage_attempts=cached_stage_attempts,
                            state_version=2,
                            active_path=self._build_active_path(
                                stage_status=cached_stage_status,
                                current_step_id=None,
                            ),
                            current_step_status_override=AgentRunStatus.SUCCEEDED.value,
                        ),
                        event_id=f"{cached_response.run.id}:3",
                        seq=3,
                    ),
                )
                yield (
                    "final",
                    self._build_terminal_event_payload(
                        status=cached_response.status,
                        run_payload=run_payload,
                        assistant_message=cached_response.assistant_message.model_dump(
                            mode="json"
                        ),
                        evidence=[item.model_dump(mode="json") for item in cached_response.evidence],
                        confidence_score=cached_response.confidence_score,
                        confidence_level=cached_response.confidence_level,
                        stage_summaries=(
                            cached_response.stage_summaries
                            if isinstance(cached_response.stage_summaries, dict)
                            else None
                        ),
                        metrics=(
                            cached_response.metrics
                            if isinstance(cached_response.metrics, dict)
                            else None
                        ),
                        source=cached_response.source,
                        cache=(
                            cached_response.cache.model_dump(mode="json")
                            if cached_response.cache is not None
                            else None
                        ),
                    ),
                )
                return
        else:
            await self._ensure_kb_chat_resume_target_valid(session=session, run=run)

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
        protocol_emit_total = 0
        protocol_drift_total = 0
        protocol_salvage_total = 0
        node_io_snapshot_truncated_count = 0
        custom_event_unhandled_count = 0
        stream_run_state = _KbChatStreamRunState(stage_status={}, stage_attempts={})
        last_good_answer: str | None = None
        last_good_answer_source: str | None = None

        def _emit_enveloped(
            *,
            event_type: str,
            payload: dict[str, Any],
            node_name: str | None = None,
            node_path: list[str] | None = None,
            attempt: int | None = None,
        ) -> tuple[str, dict[str, Any]]:
            event_seq["value"] += 1
            seq = event_seq["value"]
            nonlocal protocol_emit_total
            nonlocal protocol_drift_total
            nonlocal protocol_salvage_total
            protocol_emit_total += 1
            resolved_node_name = node_name if isinstance(node_name, str) and node_name else None
            drift_delta = 0
            salvage_used = False
            if event_type in {"messages", "updates", "node_io", "step"}:
                if resolved_node_name is None and isinstance(node_path, list) and node_path:
                    resolved_node_name = node_path[-1]
                    drift_delta += 1
                    salvage_used = True
            scoped_node_path = self._build_scoped_node_path(
                node_name=resolved_node_name,
                node_path=node_path,
            )
            if not isinstance(payload.get("ts"), str) or not str(payload.get("ts") or "").strip():
                drift_delta += 1
                salvage_used = True
            protocol_drift_total += drift_delta
            if salvage_used:
                protocol_salvage_total += 1
            node = None
            if resolved_node_name is not None:
                node = {"id": resolved_node_name, "name": resolved_node_name}
            emitted_payload = self._build_protocol_event_payload(
                event_type=event_type,
                run_id=run.id,
                payload=payload,
                node=node,
                event_id=f"{run.id}:{seq}",
                seq=seq,
                node_path=scoped_node_path,
                attempt=attempt,
            )
            return (
                event_type,
                emitted_payload,
            )

        def _emit_state(
            *,
            run_status: str,
            message: str | None = None,
            degrade_reason_value: str | None = None,
            current_step_status_override: str | None = None,
            node_path: list[str] | None = None,
        ) -> tuple[str, dict[str, Any]]:
            stream_run_state.state_version += 1
            payload = self._build_stream_state_payload(
                run_id=run.id,
                run_status=run_status,
                current_step_id=stream_run_state.current_step_id,
                current_node=stream_run_state.current_node,
                stage_status=stream_run_state.stage_status,
                stage_attempts=stream_run_state.stage_attempts,
                state_version=stream_run_state.state_version,
                active_path=self._build_active_path(
                    stage_status=stream_run_state.stage_status,
                    current_step_id=stream_run_state.current_step_id,
                ),
                last_good_answer=last_good_answer,
                degrade_reason=degrade_reason_value,
                message=message,
                current_step_status_override=current_step_status_override,
            )
            event_attempt = (
                payload.get("attempt") if isinstance(payload.get("attempt"), int) else None
            )
            return _emit_enveloped(
                event_type="state",
                payload=payload,
                node_path=node_path or [],
                attempt=event_attempt,
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
            event_seq = {"value": 0}
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
                    event_id=f"{run.id}:0",
                    seq=0,
                ),
            )
            yield _emit_state(
                run_status=AgentRunStatus.RUNNING.value,
                message="知识库问答开始",
            )

            compiled = exec_ctx.compiled_graph
            if compiled is None:
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
            if exec_ctx.resume_checkpoint_id is not None:
                configurable = (
                    dict(config.get("configurable"))
                    if isinstance(config.get("configurable"), dict)
                    else {}
                )
                configurable["checkpoint_id"] = exec_ctx.resume_checkpoint_id
                config = {**config, "configurable": configurable}
            stream = compiled.astream(
                build_graph_input_state(exec_ctx.state),
                config,
                context=exec_ctx.run_context,
                **self._build_graph_stream_options(),
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

            while True:
                if disconnect_event.is_set():
                    await _cancel_graph()
                    await self._persist_guardrail_run(
                        exec_ctx=exec_ctx,
                        run=run,
                        status=AgentRunStatus.FAILED,
                        reason="errterm_client_disconnect",
                        stream_state=stream_state,
                    )
                    self._release_retrieval_buffer(exec_ctx)
                    yield _emit_state(
                        run_status=AgentRunStatus.FAILED.value,
                        message="client disconnected before stream completed",
                        current_step_status_override=AgentRunStatus.FAILED.value,
                    )
                    yield (
                        "error",
                        {
                            "code": "CHAT_STREAM_TERMINATED",
                            "message": "client disconnected before stream completed",
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
                            status=AgentRunStatus.FAILED,
                            reason="errterm_client_disconnect",
                            stream_state=stream_state,
                        )
                        self._release_retrieval_buffer(exec_ctx)
                        yield _emit_state(
                            run_status=AgentRunStatus.FAILED.value,
                            message="client disconnected before stream completed",
                            current_step_status_override=AgentRunStatus.FAILED.value,
                        )
                        yield (
                            "error",
                            {
                                "code": "CHAT_STREAM_TERMINATED",
                                "message": "client disconnected before stream completed",
                            },
                        )
                        return
                    disconnect_task = None

                if queue_task not in done:
                    continue

                kind, payload = queue_task.result()
                if kind == "event":
                    mode, chunk, node_path = payload

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
                            if node_name is None and isinstance(node_path, list) and node_path:
                                node_name = node_path[-1]
                            yield _emit_enveloped(
                                event_type="messages",
                                payload={
                                    "run_id": str(run.id),
                                    "node": node_name,
                                    "deltas": [delta.to_dict() for delta in deltas],
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                },
                                node_name=node_name,
                                node_path=node_path or [],
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
                        if candidate_node is None and isinstance(node_path, list) and node_path:
                            candidate_node = node_path[-1]
                        interrupts = apply_updates_chunk(stream_state, chunk)
                        candidate, candidate_source = self._extract_last_good_answer(
                            answer="",
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
                            node_path=node_path or [],
                        )
                        continue

                    if mode == "tasks" and isinstance(chunk, dict):
                        step_payload = self._build_step_payload_from_task_event(
                            payload=chunk,
                            node_path=node_path,
                        )
                        if step_payload is None:
                            continue
                        node_name = self._apply_stream_state_step(
                            stream_state=stream_run_state,
                            payload=step_payload,
                            node_path=node_path,
                        )
                        event_attempt = (
                            stream_run_state.stage_attempts.get(node_name)
                            if isinstance(node_name, str) and node_name
                            else None
                        )
                        yield _emit_enveloped(
                            event_type="step",
                            payload=step_payload,
                            node_name=node_name,
                            node_path=node_path or [],
                            attempt=event_attempt if isinstance(event_attempt, int) else None,
                        )
                        yield _emit_state(
                            run_status=AgentRunStatus.RUNNING.value,
                            message=(
                                step_payload.get("message")
                                if isinstance(step_payload.get("message"), str)
                                else None
                            ),
                            node_path=node_path or [],
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
                            custom_event_type = (
                                payload_dict.get("event_type")
                                if isinstance(payload_dict.get("event_type"), str)
                                else "custom"
                            )
                            if custom_event_type not in KB_CHAT_CUSTOM_EVENT_TYPES:
                                custom_event_unhandled_count += 1
                            emitted_event_type = (
                                "node_io" if custom_event_type == "node_io" else "custom"
                            )
                            event_attempt = (
                                payload_dict.get("attempt")
                                if isinstance(payload_dict.get("attempt"), int)
                                else None
                            )
                            if custom_event_type == "node_io":
                                node_name = self._apply_stream_state_node_io(
                                    stream_state=stream_run_state,
                                    payload=payload_dict,
                                    node_path=node_path,
                                )
                                execution_id = self._resolve_stream_execution_id(
                                    stream_state=stream_run_state,
                                    payload=payload_dict,
                                    node_name=node_name,
                                    node_path=node_path,
                                )
                                if execution_id is not None:
                                    payload_dict["execution_id"] = execution_id
                                    payload_dict.setdefault("task_id", execution_id)
                                    self._remember_stream_execution(
                                        stream_state=stream_run_state,
                                        execution_id=execution_id,
                                        node_name=node_name,
                                        node_path=node_path,
                                    )
                                for meta_key in ("input_snapshot_meta", "output_snapshot_meta"):
                                    meta = payload_dict.get(meta_key)
                                    if isinstance(meta, dict) and meta.get("truncated") is True:
                                        node_io_snapshot_truncated_count += 1
                            yield _emit_enveloped(
                                event_type=emitted_event_type,
                                payload=payload_dict,
                                node_name=node_name,
                                node_path=node_path or [],
                                attempt=event_attempt,
                            )
                            if custom_event_type == "node_io" and node_name is not None:
                                error_message = (
                                    payload_dict.get("error_summary")
                                    if payload_dict.get("phase") == "error"
                                    and isinstance(payload_dict.get("error_summary"), str)
                                    else None
                                )
                                yield _emit_state(
                                    run_status=AgentRunStatus.RUNNING.value,
                                    message=error_message,
                                    node_path=node_path or [],
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

            protocol_metrics = self._build_protocol_metrics(
                protocol_emit_total=protocol_emit_total,
                protocol_required_field_drift_count=protocol_drift_total,
                protocol_salvage_count=protocol_salvage_total,
                node_io_snapshot_truncated_count=node_io_snapshot_truncated_count,
                custom_event_unhandled_count=custom_event_unhandled_count,
                heartbeat_stats=sse_heartbeat_stats,
            )
            stream_state.metrics = {
                **(stream_state.metrics if isinstance(stream_state.metrics, dict) else {}),
                **protocol_metrics,
            }

            metrics, stage_summaries = self._build_observability(
                kb_chat_config=exec_ctx.kb_chat_config,
                history_usage=exec_ctx.history_usage,
                history_truncation=exec_ctx.history_truncation,
                retrieval_meta=exec_ctx.retrieval_meta,
                retrieval_results=exec_ctx.retrieval_results,
                base_metrics=stream_state.metrics,
                base_stage_summaries=stream_state.stage_summaries,
                stage_attempts=stream_run_state.stage_attempts,
            )
            metrics = self._apply_guardrail_metrics(
                metrics=metrics,
                stage_summaries=stage_summaries,
                kb_scope=exec_ctx.retrieval_meta.get("kb_scope")
                if isinstance(exec_ctx.retrieval_meta, dict)
                else None,
            )

            clarification_message, pending_clarification = self._extract_clarification_pending(
                clarification_payload=stream_state.clarification_payload,
                answer=answer,
                reflection=stream_state.reflection,
            )
            candidate, candidate_source = self._extract_last_good_answer(
                answer=answer,
                stream_state=stream_state,
            )
            if candidate:
                last_good_answer = candidate
                last_good_answer_source = candidate_source

            terminal_candidate = "out202" if clarification_message is not None else "status"
            yield _emit_enveloped(
                event_type="stream_end",
                payload={
                    "run_id": str(run.id),
                    "terminal_candidate": terminal_candidate,
                    "answer_preview": answer[:200],
                    "stage_summaries": stage_summaries,
                    "metrics": metrics,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )

            if clarification_message is not None:
                max_rounds = max(
                    0,
                    int(getattr(self._settings, "kb_chat_max_clarification_rounds", 1)),
                )
                current_rounds = self._clarification_round_count(
                    run.metrics if isinstance(run.metrics, dict) else None
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
                    run_payload = pending_response.run.model_dump(mode="json")
                    yield _emit_state(
                        run_status="waiting_user",
                        message=pending_response.message,
                        current_step_status_override="waiting_user",
                    )
                    yield (
                        "interrupt",
                        self._build_terminal_event_payload(
                            status=pending_response.status,
                            run_payload=run_payload,
                            assistant_message=None,
                            evidence=[],
                            confidence_score=pending_response.confidence_score,
                            confidence_level=pending_response.confidence_level,
                            stage_summaries=(
                                pending_response.stage_summaries
                                if isinstance(pending_response.stage_summaries, dict)
                                else None
                            ),
                            metrics=(
                                pending_response.metrics
                                if isinstance(pending_response.metrics, dict)
                                else None
                            ),
                            message=pending_response.message,
                            pending_clarification=(
                                pending_response.pending_clarification.model_dump(mode="json")
                                if pending_response.pending_clarification is not None
                                else None
                            ),
                            source=pending_response.source,
                            cache=(
                                pending_response.cache.model_dump(mode="json")
                                if pending_response.cache is not None
                                else None
                            ),
                        ),
                    )
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
                answer=answer,
                clarification_payload=stream_state.clarification_payload,
                routing_decisions=stream_state.routing_decisions,
                reflection=stream_state.reflection,
                best_answer=stream_state.best_answer,
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
                best_answer_meta=stream_state.best_answer_meta,
                loop_counts=stream_state.loop_counts,
            )
            final_response = await self._finalize_run(
                session=session,
                run=run,
                kb_chat_config=exec_ctx.kb_chat_config,
                started_at=exec_ctx.started_at,
                answer=answer,
                retrieval_results=exec_ctx.retrieval_results,
                evidence_draft_items_by_round=exec_ctx.evidence_draft_items_by_round,
                preferred_evidence_round=preferred_evidence_round,
                stage_summaries=stage_summaries,
                metrics=metrics,
                status=terminal_status,
                error_message=terminal_message,
                terminal_reason=self._resolve_terminal_reason(
                    clarification_payload=stream_state.clarification_payload,
                    routing_decisions=stream_state.routing_decisions,
                    reflection=stream_state.reflection,
                    degrade_reason=stream_state.degrade_reason,
                ),
                clarification_payload=stream_state.clarification_payload,
                confidence_score=stream_state.confidence_score,
                confidence_level=stream_state.confidence_level,
                reflection=stream_state.reflection,
                query_strategy=stream_state.query_strategy,
                routing_decisions=stream_state.routing_decisions,
            )
            run_payload = final_response.run.model_dump(mode="json")
            yield _emit_state(
                run_status=final_response.status,
                message=terminal_message,
                degrade_reason_value=terminal_message,
                current_step_status_override=final_response.status,
            )
            yield (
                "final",
                self._build_terminal_event_payload(
                    status=final_response.status,
                    run_payload=run_payload,
                    assistant_message=final_response.assistant_message.model_dump(mode="json"),
                    evidence=[item.model_dump(mode="json") for item in final_response.evidence],
                    confidence_score=final_response.confidence_score,
                    confidence_level=final_response.confidence_level,
                    stage_summaries=(
                        final_response.stage_summaries
                        if isinstance(final_response.stage_summaries, dict)
                        else None
                    ),
                    metrics=(
                        final_response.metrics
                        if isinstance(final_response.metrics, dict)
                        else None
                    ),
                    source=final_response.source,
                    cache=(
                        final_response.cache.model_dump(mode="json")
                        if final_response.cache is not None
                        else None
                    ),
                ),
            )

        except asyncio.CancelledError:
            await _cancel_graph()
            await self._persist_guardrail_run(
                exec_ctx=exec_ctx,
                run=run,
                status=AgentRunStatus.FAILED,
                reason="errterm_cancelled",
                stream_state=stream_state,
            )
            self._release_retrieval_buffer(exec_ctx)
            raise
        except Exception as e:
            await _cancel_graph()
            run.status = AgentRunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            error_summary = e.message if isinstance(e, AppError) else str(e)
            run.error_message = error_summary
            run.stage_summaries = {
                **(run.stage_summaries if isinstance(run.stage_summaries, dict) else {}),
                "errterm": {
                    "reason": "stream_exception",
                    "message": error_summary,
                    "at": run.finished_at.isoformat(),
                },
            }
            await self._db.commit()
            self._release_retrieval_buffer(exec_ctx)
            yield _emit_state(
                run_status=AgentRunStatus.FAILED.value,
                message=error_summary,
                degrade_reason_value=error_summary,
                current_step_status_override=AgentRunStatus.FAILED.value,
            )
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
        kb_chat_config: KbChatConfig,
        started_at: datetime,
        answer: str,
        retrieval_results: list,
        evidence_draft_items_by_round: dict[int, list[dict[str, Any]]] | None = None,
        preferred_evidence_round: int | None = None,
        stage_summaries: dict[str, Any],
        metrics: dict[str, Any],
        status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
        error_message: str | None = None,
        terminal_reason: str | None = None,
        clarification_payload: dict[str, Any] | None = None,
        confidence_score: float | None = None,
        confidence_level: str | None = None,
        reflection: dict[str, Any] | None = None,
        query_strategy: str | None = None,
        routing_decisions: dict[str, Any] | None = None,
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
        allow_no_evidence = terminal_reason == "clarify" or isinstance(
            clarification_payload, dict
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
                reason_code=terminal_reason,
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
                    user_id=self._resolve_kb_chat_user_id(session),
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
        latency_ms = int((run.finished_at - started_at).total_seconds() * 1000)
        route_consistency_rate = self._compute_route_consistency(
            query_strategy=query_strategy,
            routing_decisions=routing_decisions,
        )
        final_state_consistency_rate = self._compute_final_state_consistency(
            routing_decisions=routing_decisions,
            terminal_reason=terminal_reason,
        )
        clarification_consistency_rate = self._compute_clarification_consistency(
            metrics=metrics,
            clarification_payload=clarification_payload,
            terminal_reason=terminal_reason,
        )
        protocol_required_field_drift_rate = float(
            metrics.get("protocol_required_field_drift_rate") or 0.0
        )
        p95_latency_increase_pct = await self._compute_p95_latency_increase_pct(
            current_latency_ms=latency_ms,
        )
        metrics = {
            **metrics,
            "route_consistency_rate": route_consistency_rate,
            "final_state_consistency_rate": final_state_consistency_rate,
            "clarification_consistency_rate": clarification_consistency_rate,
            "p95_latency_increase_pct": p95_latency_increase_pct,
            "protocol_required_field_drift_rate": protocol_required_field_drift_rate,
            "gray_release_indicators": {
                "route_consistency_rate": route_consistency_rate,
                "final_state_consistency_rate": final_state_consistency_rate,
                "clarification_consistency_rate": clarification_consistency_rate,
                "p95_latency_increase_pct": p95_latency_increase_pct,
                "protocol_required_field_drift_rate": protocol_required_field_drift_rate,
            },
        }
        gray_release_gate = self._build_gray_release_gate(metrics)
        gray_release_gate["source_run_id"] = str(run.id)
        gray_release_gate["evaluated_at"] = run.finished_at.isoformat()
        gray_release_gate["trigger_rollback"] = (
            bool(getattr(self._settings, "kb_chat_gray_release_auto_rollback_enabled", True))
            and gray_release_gate.get("pass") is False
        )
        metrics["gray_release_gate"] = gray_release_gate
        stage_summaries = {**stage_summaries, "gray_release_gate": gray_release_gate}
        self._persist_gray_release_anomaly_sample(
            run_id=run.id,
            gate=gray_release_gate,
            metrics=metrics,
            stage_summaries=stage_summaries,
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
            "latency_ms": latency_ms,
            **summary_metrics,
            **metrics,
        }

        await self._db.commit()
        await self._db.refresh(assistant_msg)
        await self._db.refresh(run)

        if isinstance(confidence_score, (int, float)):
            confidence_score = max(0.0, min(1.0, float(confidence_score)))
        else:
            confidence_score = None
        if not isinstance(confidence_level, str) or confidence_level not in {
            "high",
            "medium",
            "low",
        }:
            confidence_level = None
        if confidence_level is None and confidence_score is not None:
            if confidence_score >= 0.8:
                confidence_level = "high"
            elif confidence_score >= 0.5:
                confidence_level = "medium"
            else:
                confidence_level = "low"

        semantic_cache_skip_reason = self._semantic_cache_skip_reason(
            clarification_payload=clarification_payload,
            routing_decisions=routing_decisions,
            reflection=reflection if isinstance(reflection, dict) else None,
            degrade_reason=terminal_reason,
            answer=answer,
        )
        if status == AgentRunStatus.SUCCEEDED and semantic_cache_skip_reason is None:
            try:
                await self._write_semantic_cache_entry(
                    session=session,
                    kb_chat_config=kb_chat_config,
                    question=str(run.question or "").strip(),
                    answer=extract_answer_text(answer),
                    evidence=evidence_items,
                    confidence_score=confidence_score,
                    confidence_level=confidence_level,
                    stage_summaries=(
                        run.stage_summaries if isinstance(run.stage_summaries, dict) else {}
                    ),
                    metrics=run.metrics if isinstance(run.metrics, dict) else {},
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("语义缓存写入失败: %s", exc)

        return ChatAnswerResponse(
            assistant_message=ChatMessageRead.model_validate(assistant_msg),
            evidence=evidence_items,
            confidence_score=confidence_score,
            confidence_level=cast(Literal["high", "medium", "low"] | None, confidence_level),
            source="live",
            cache=SemanticCacheMeta(
                hit=False,
                threshold=self._semantic_cache_threshold(),
                ttl_seconds=self._semantic_cache_ttl_seconds(),
            ),
            stage_summaries=run.stage_summaries if isinstance(run.stage_summaries, dict) else None,
            metrics=run.metrics if isinstance(run.metrics, dict) else None,
            run=AgentRunRead.model_validate(run),
        )
