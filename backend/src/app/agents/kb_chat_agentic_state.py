"""KB Chat agentic graph state (structured + checkpointer-friendly)."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages

# -----------------------------
# Query bundle types
# -----------------------------

from app.schemas.query_enhancement import QueryItem


# -----------------------------
# Reflection / budget / metrics
# -----------------------------

ReflectionAction = Literal["none", "clarify", "transform_query", "generate", "force_exit"]


class ReflectionResult(TypedDict, total=False):
    """Outputs from reflection layer graders (serializable)."""

    relevance_passed: bool
    review_passed: bool
    action: ReflectionAction
    reason: str
    reason_code: str
    confidence: float
    evidence_score: float
    decision_source: str
    risk_level: str
    retry_advice: str
    hint: str


class LoopCounts(TypedDict):
    """Loop counters used for budget control."""

    total_rounds: int
    retrieval_retries: int
    generation_retries: int


class MemoryKeys(TypedDict, total=False):
    """Namespacing keys used by store/checkpointer (all strings for portability)."""

    user_id: str
    thread_id: str
    kb_ids: list[str]


class KbChatRuntimeConfig(TypedDict, total=False):
    """Per-session runtime feature toggles for KB answer chain."""

    query_rewrite_enabled: bool
    ambiguity_check_enabled: bool
    normalize_llm_enabled: bool
    normalize_alias_max: int
    normalize_timeout_seconds: float
    hyde_enabled: bool
    entity_expand_enabled: bool
    entity_expand_max_candidates: int
    entity_expand_max_variants: int
    entity_expand_min_confidence: float
    entity_expand_timeout_seconds: float
    parallel_retrieval_enabled: bool
    parallel_retrieval_min_queries: int
    parallel_retrieval_max_branches: int
    parallel_retrieval_include_main: bool
    rewrite_branch_enabled: bool
    rewrite_branch_max_candidates: int
    rewrite_min_confidence: float
    doc_gate_rule_threshold: float
    doc_gate_llm_confidence_floor: float
    doc_gate_fallback_open_when_evidence_ok: bool
    doc_gate_cache_ttl_seconds: int
    hybrid_retrieval_enabled: bool
    rerank_enabled: bool
    retrieval_top_k: int
    retrieval_rerank_top_k: int
    retrieval_hybrid_ranker: Literal["rrf", "weighted"]
    retrieval_hybrid_dense_weight: float
    retrieval_hybrid_sparse_weight: float
    retrieval_hybrid_rrf_k: int
    retrieval_parent_max_parents: int
    retrieval_parent_max_children_per_parent: int
    retrieval_multiscale_per_window_top_k: int
    retrieval_multiscale_rrf_k: int
    retrieval_multiscale_max_documents: int
    retrieval_multiscale_max_chunks_per_document: int


class ContextTurn(TypedDict):
    """A recent dialogue turn for display/debugging."""

    role: Literal["user", "assistant"]
    text: str


class ContextFrame(TypedDict, total=False):
    """Structured context assembled before rewrite/retrieval."""

    summary_text: str
    summary_source: Literal["persisted", "generated", "none"]
    recent_turns: list[ContextTurn]
    selected_turns: list[ContextTurn]
    memory_snippet: str
    current_question: str
    merge_strategy: Literal["builtin_summary_first"]
    merge_fallback_used: bool
    merge_notes: list[str]


class CorefMeta(TypedDict, total=False):
    triggered: bool
    confidence: float
    candidate_count: int
    selected_mention: str
    resolution_source: str
    apply_strategy: str
    needs_clarification: bool
    clarification_hint: str


class ClarificationSlot(TypedDict, total=False):
    key: str
    label: str
    required: bool
    options: list[str]


class ClarificationPayload(TypedDict, total=False):
    question: str
    reason_code: Literal[
        "missing_entity",
        "missing_scope",
        "missing_time",
        "missing_metric",
        "coref_uncertain",
        "mixed",
    ]
    confidence: float
    model_reason: str
    slots: list[ClarificationSlot]
    suggested_answers: list[str]


class NormalizeMeta(TypedDict, total=False):
    source: str
    fallback_reason: str
    aliases: list[str]
    entities: list[str]
    time_constraints: list[str]
    metric_constraints: list[str]
    scope_constraints: list[str]
    recall_risk: Literal["low", "medium", "high"]
    drift_risk: bool
    reasoning: str
    constraint_preserved: bool


class MessagePlanCandidate(TypedDict, total=False):
    index: int
    kind: str
    query: str
    source: str
    priority: int
    quality_score: float


class MessagePlan(TypedDict, total=False):
    strategy: Literal["direct", "decomposition", "multi_query"]
    candidates: list[MessagePlanCandidate]
    selected: list[MessagePlanCandidate]
    dropped: list[dict[str, Any]]
    budget: dict[str, Any]


class QueryBundle(TypedDict, total=False):
    items: list[QueryItem]
    kind_breakdown: dict[str, int]
    dedup_stats: dict[str, int]


class PrepareDiagnostics(TypedDict, total=False):
    quality_signals: list[str]
    fallback_reason: str
    timing: dict[str, Any]


class SubqueryRun(TypedDict, total=False):
    subquery_id: str
    index: int
    query: str
    query_used: str
    kind: str
    priority: int
    purpose: str
    coverage_tags: list[str]
    context: str
    used_query_item_bundle: bool
    retrieval_count: int
    success: bool
    reason: str | None


class RetrievalPlan(TypedDict, total=False):
    mode: Literal["single_retrieve", "parallel_fanout"]
    branch_count: int
    rank_strategy: str
    selected_queries: list[str]
    reason: str


class RewritePlan(TypedDict, total=False):
    version: str
    selected_query: str
    selected_candidate_id: str
    candidates: list[dict[str, Any]]
    strategy: str
    confidence: float
    reason: str
    fallback_reason: str
    risk_flags: list[str]


class RewriteBranchRun(TypedDict, total=False):
    candidate_id: str
    query: str
    source: str
    priority: int
    retrieval_count: int
    success: bool
    reason: str | None


class RewriteDiagnostics(TypedDict, total=False):
    decision_path: str
    fallback_reason: str
    selected_candidate_id: str
    selected_query: str
    branch_count: int
    confidence: float
    min_confidence: float
    retry_count: int
    cache_hit: bool
    notes: list[str]


# -----------------------------
# Graph state schema
# -----------------------------

class KbChatAgenticStateBase(TypedDict):
    """Required fields for agentic KB chat runs."""

    # NOTE: LangGraph provides special reducers for message lists.
    messages: Annotated[list[AnyMessage], add_messages]

    # Raw user question (unmodified).
    user_input: str

    # Keep compatibility with existing streaming/service plumbing.
    pending_tool_calls: list[dict]

    # Budget / observability (kept compatible with existing AgentRun fields).
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]

    # Store/checkpointer namespace (values are JSON-friendly).
    memory_keys: MemoryKeys
    runtime_config: KbChatRuntimeConfig


class KbChatAgenticState(KbChatAgenticStateBase, total=False):
    """Optional fields populated across stages.

    Stage I/O (high-level, to keep implementation honest):
    - MergeContext: reads messages/user_input/memory_keys -> writes
      context_frame/rewrite_input_query/display_context/merged_context
    - CorefRewrite: reads rewrite_input_query/context_frame -> writes coref_query/coref_meta
    - AmbiguityCheck: reads coref_query/normalized_query -> writes reflection/action (clarify)
    - NormalizeRewrite: reads coref_query -> writes normalized_query
    - ComplexityRouter: reads normalized_query -> writes query_strategy/confidence/signals
    - Decomposition: reads normalized_query -> writes sub_queries
    - MultiQuery: reads normalized_query -> writes multi_queries
    - HyDE: reads normalized_query -> writes hyde_docs
    - QueryBundle: reads query family -> writes
      message_plan/query_bundle/prepare_diagnostics/query_items
    - RetrievalLayer: reads query family -> writes final_context/metrics
    - ReflectionLayer: reads final_context -> writes reflection (+ optional rewritten query)
    - AnswerSubgraph: reads final_context -> writes draft_answer/final_answer/review
    """

    context_frame: ContextFrame
    rewrite_input_query: str
    display_context: str
    merged_context: str

    coref_query: str
    coref_meta: CorefMeta
    normalized_query: str
    normalized_meta: NormalizeMeta
    entity_expand_meta: dict[str, Any]
    query_strategy: Literal["direct", "decomposition", "multi_query"]
    query_strategy_confidence: float
    query_strategy_signals: list[str]
    rewrite_plan: RewritePlan
    rewrite_diagnostics: RewriteDiagnostics
    rewrite_branch_runs: Annotated[list[RewriteBranchRun], add]
    decomposition_plan: dict[str, Any]

    sub_queries: list[str]
    multi_queries: list[str]
    hyde_docs: list[str]
    message_plan: MessagePlan
    query_bundle: QueryBundle
    prepare_diagnostics: PrepareDiagnostics
    retrieval_plan: RetrievalPlan
    query_items: list[QueryItem]
    subquery_runs: Annotated[list[SubqueryRun], add]
    subquery_task: dict[str, Any]

    final_context: str
    draft_answer: str
    final_answer: str
    best_answer: str
    best_answer_meta: dict[str, Any]
    answer_subgraph_state: dict[str, Any]
    answer_quality: dict[str, Any]
    degrade_reason: str
    clarification_payload: ClarificationPayload

    doc_gate_state: dict[str, Any]
    reflection: ReflectionResult


def make_initial_state(
    *,
    user_input: str,
    messages: list[AnyMessage] | None = None,
    memory_keys: MemoryKeys | None = None,
    runtime_config: KbChatRuntimeConfig | None = None,
) -> KbChatAgenticState:
    """Create a minimal, serializable initial state for an agentic KB chat run."""

    return {
        "messages": messages or [],
        "user_input": user_input,
        "pending_tool_calls": [],
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
        "metrics": {},
        "memory_keys": memory_keys or {},
        "runtime_config": runtime_config or {},
        # Pre-initialize list fields to reduce KeyError risk in early node work.
        "sub_queries": [],
        "multi_queries": [],
        "hyde_docs": [],
        "entity_expand_meta": {},
        "message_plan": {
            "strategy": "direct",
            "candidates": [],
            "selected": [],
            "dropped": [],
            "budget": {},
        },
        "query_bundle": {
            "items": [],
            "kind_breakdown": {},
            "dedup_stats": {},
        },
        "prepare_diagnostics": {
            "quality_signals": [],
            "fallback_reason": "none",
            "timing": {},
        },
        "rewrite_plan": {
            "version": "kb_chat_rewrite_plan_v1",
            "selected_query": "",
            "selected_candidate_id": "",
            "candidates": [],
            "strategy": "single",
            "confidence": 0.0,
            "reason": "init",
            "fallback_reason": "none",
            "risk_flags": [],
        },
        "rewrite_diagnostics": {
            "decision_path": "init",
            "fallback_reason": "none",
            "selected_candidate_id": "",
            "selected_query": "",
            "branch_count": 0,
            "confidence": 0.0,
            "min_confidence": 0.0,
            "retry_count": 0,
            "cache_hit": False,
            "notes": [],
        },
        "query_items": [],
        "rewrite_branch_runs": [],
        "subquery_runs": [],
        "answer_subgraph_state": {},
        "decomposition_plan": {
            "strategy": "direct",
            "version": "kb_chat_decomposition_plan_v2",
            "sub_query_specs": [],
            "risk_flags": [],
            "reasoning": "",
        },
        "doc_gate_state": {},
    }
