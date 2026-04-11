from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.kb_chat_agentic_graph import KbChatAgenticGraph, KbChatGraphContext
from app.agents.kb_chat_agentic_state import KbChatInternalState
from app.models.agent_run import AgentRun
from app.schemas.chats import KbChatConfig

_STREAM_EVENT_VERSION = "2.0"
_GRAY_ROUTE_THRESHOLD = 99.5
_GRAY_FINAL_THRESHOLD = 99.0
_GRAY_CLARIFICATION_THRESHOLD = 99.0
_GRAY_P95_THRESHOLD = 10.0
_SEMANTIC_CACHE_PRE_CONTEXT_MAX_TURNS = 6
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
    "evidence_items",
    "citation_catalog",
    "compression_stats",
    "draft_answer",
    "final_answer",
    "best_answer",
    "best_answer_meta",
    "answer_subgraph_state",
    "degrade_reason",
    "clarification_payload",
    "answer_review_runs",
    "reflection",
    "routing_decisions",
)


def _gray_release_log_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "logs" / "kb_chat_gray_release"


def _as_str_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass
class _KbRetrievalBuffer:
    results: list
    meta: dict[str, Any]

    def release(self) -> None:
        self.results.clear()
        self.meta.clear()


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
    retrieval_meta: dict[str, Any]
    retrieval_buffer: _KbRetrievalBuffer
    graph: KbChatAgenticGraph
    compiled_graph: Any | None
    state: KbChatInternalState
    run_context: KbChatGraphContext | None
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