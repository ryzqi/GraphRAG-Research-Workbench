"""KB Chat agentic graph state (structured + checkpointer-friendly)."""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.agents.kb_chat_contracts import STATE_SCHEMA_V3

# -----------------------------
# Query bundle types
# -----------------------------

from app.schemas.query_enhancement import QueryItem


# -----------------------------
# Reflection / budget / metrics
# -----------------------------

ReflectionAction = Literal["none", "clarify", "transform_query", "force_exit"]
ComplexityLevel = Literal["simple", "moderate", "complex"]


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
    review_breakdown: dict[str, Any]
    review_risk_level: str
    review_confidence: float
    review_decision_source: str


class RoutingDecision(TypedDict, total=False):
    """Canonical routing record for cross-node / cross-subgraph decisions."""

    phase: str
    next_node: str
    action: str
    reason: str
    reason_code: str
    decision_source: str
    retry_advice: str
    score: float
    retry_budget_snapshot: dict[str, int]
    round_id: int
    completed_at: str


class LoopCounts(TypedDict):
    """Loop counters used for budget control."""

    total_rounds: int
    retrieval_retries: int
    generation_retries: int


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


class QueryPlanFallbackPolicy(TypedDict, total=False):
    allow_broaden: bool
    allow_hyde: bool
    allow_retry_rewrite: bool


class QueryPlanResult(TypedDict, total=False):
    strategy: Literal["direct", "paraphrase", "decomposition", "multi_query"]
    reasoning: str
    fallback_policy: QueryPlanFallbackPolicy


class QueryPlanDiagnostics(TypedDict, total=False):
    candidate_count: int
    selected_count: int
    fallback_reason: str
    latency_ms: int
    rejection_counts: dict[str, int]


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
    retrieval_round: int
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


class AnswerReviewRun(TypedDict, total=False):
    review_round: int
    check: str
    passed: bool
    reason: str
    confidence: float
    fallback_reason: str | None
    decision_source: str
    latency_ms: int


# -----------------------------
# Graph state schema
# -----------------------------

class KbChatInputState(TypedDict):
    """Minimal public graph input for a KB chat turn."""

    # NOTE: LangGraph provides special reducers for message lists.
    messages: Annotated[list[AnyMessage], add_messages]

    # Raw user question (unmodified).
    user_input: str


class KbChatOutputState(TypedDict, total=False):
    """Minimal public graph output exposed to service consumers."""

    final_answer: str
    clarification_payload: ClarificationPayload
    stage_summaries: dict[str, Any]


class KbChatInternalStateBase(KbChatInputState):
    """Required internal fields for agentic KB chat runs."""

    schema_version: str

    # Keep compatibility with existing streaming/service plumbing.
    pending_tool_calls: list[dict]

    # Budget / observability (kept compatible with existing AgentRun fields).
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]


class KbChatInternalState(KbChatInternalStateBase, total=False):
    """Optional fields populated across stages.

    Stage I/O (high-level, to keep implementation honest):
    - MergeContext: reads messages/user_input/memory_keys -> writes
      context_frame/rewrite_input_query/merged_context
    - ResolveReference: reads rewrite_input_query/context_frame -> writes
      resolved_query/reference_resolution_meta
    - AmbiguityCheck: reads resolved_query/normalized_query -> writes reflection/action (clarify)
    - QueryNormalize: reads resolved_query -> writes normalized_query
    - QueryPlan: reads normalized_query -> writes query_strategy + routes to restored enhancement nodes
    - QueryPlanFinalize: reads query family artifacts -> writes
      query_plan_result/query_plan_diagnostics/query_items
    - RetrievalLayer: reads query family -> writes final_context/metrics
    - ReflectionLayer: reads final_context -> writes reflection (+ optional rewritten query)
    - AnswerSubgraph: reads final_context -> writes draft_answer/final_answer/review
    """

    context_frame: ContextFrame
    rewrite_input_query: str
    merged_context: str

    resolved_query: str
    reference_resolution_meta: CorefMeta
    coref_query: str
    coref_meta: CorefMeta
    normalized_query: str
    normalized_meta: NormalizeMeta
    query_strategy: Literal["direct", "paraphrase", "decomposition", "multi_query"]
    complexity_level: ComplexityLevel
    query_strategy_confidence: float
    query_strategy_signals: list[str]
    sub_queries: list[str]
    multi_queries: list[str]
    hyde_docs: list[str]
    decomposition_plan: dict[str, Any]
    entity_expand_meta: dict[str, Any]
    query_plan_result: QueryPlanResult
    query_plan_diagnostics: QueryPlanDiagnostics
    retrieval_plan: RetrievalPlan
    retrieval_budget: dict[str, Any]
    retrieval_diagnostics: dict[str, float]
    query_items: list[QueryItem]
    subquery_runs: Annotated[list[SubqueryRun], add]
    subquery_task: dict[str, Any]

    final_context: str
    compression_stats: dict[str, Any]
    draft_answer: str
    final_answer: str
    best_answer: str
    best_answer_meta: dict[str, Any]
    answer_subgraph_state: dict[str, Any]
    degrade_reason: str
    clarification_payload: ClarificationPayload

    answer_review_runs: Annotated[list[AnswerReviewRun], add]
    reflection: ReflectionResult
    routing_decisions: dict[str, RoutingDecision]


class KbChatEmptyState(TypedDict, total=False):
    """Explicit empty read-side schema for nodes that ignore graph state."""


class StageSummaryInput(TypedDict, total=False):
    stage_summaries: dict[str, Any]


class MergeContextInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    memory_keys: dict[str, Any]
    metrics: dict[str, Any]


class CorefRewriteInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    rewrite_input_query: str
    context_frame: ContextFrame
    stage_summaries: dict[str, Any]


class AmbiguityCheckInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    resolved_query: str
    reference_resolution_meta: CorefMeta
    coref_query: str
    coref_meta: CorefMeta
    stage_summaries: dict[str, Any]


class NormalizeRewriteInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    resolved_query: str
    coref_query: str
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class QueryPlanFinalizeInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    normalized_meta: NormalizeMeta
    query_strategy: Literal["direct", "decomposition", "multi_query"]
    decomposition_plan: dict[str, Any]
    sub_queries: list[str]
    multi_queries: list[str]
    hyde_docs: list[str]
    reflection: ReflectionResult
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class QueryPlanInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    normalized_meta: NormalizeMeta
    reflection: ReflectionResult
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class DecompositionInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    normalized_query: str
    stage_summaries: dict[str, Any]


class GenerateVariantsInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    normalized_query: str
    normalized_meta: NormalizeMeta
    stage_summaries: dict[str, Any]


class EntityExpandInput(TypedDict, total=False):
    multi_queries: list[str]
    normalized_query: str
    normalized_meta: NormalizeMeta
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class HydeInput(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    normalized_query: str
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]


class RetrievalBudgetPlanInput(TypedDict, total=False):
    complexity_level: ComplexityLevel
    query_items: list[QueryItem]
    reflection: ReflectionResult
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]


class DispatchSubqueriesInput(TypedDict, total=False):
    query_strategy: Literal["direct", "paraphrase", "decomposition", "multi_query"]
    query_items: list[QueryItem]
    sub_queries: list[str]
    decomposition_plan: dict[str, Any]
    memory_keys: dict[str, Any]
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class RetrieveSubqueryContextInput(TypedDict, total=False):
    subquery_task: dict[str, Any]
    loop_counts: LoopCounts
    retrieval_budget: dict[str, Any]
    memory_keys: dict[str, Any]
    runtime_config: dict[str, Any]


class MergeSubqueryContextInput(TypedDict, total=False):
    subquery_runs: list[SubqueryRun]
    loop_counts: LoopCounts
    metrics: dict[str, Any]
    memory_keys: dict[str, Any]
    stage_summaries: dict[str, Any]


class RetrieveContextInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    query_items: list[QueryItem]
    loop_counts: LoopCounts
    metrics: dict[str, Any]
    retrieval_budget: dict[str, Any]
    memory_keys: dict[str, Any]
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class CompressContextInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    final_context: str
    stage_summaries: dict[str, Any]


class TransformQueryInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    draft_answer: str
    reflection: ReflectionResult
    loop_counts: LoopCounts
    runtime_config: dict[str, Any]
    stage_summaries: dict[str, Any]


class PreprocessRoutingInput(TypedDict, total=False):
    routing_decisions: dict[str, RoutingDecision]


class AnswerRoutingDecisionInput(TypedDict, total=False):
    routing_decisions: dict[str, RoutingDecision]
    loop_counts: LoopCounts


class AnswerReviewDispatchInput(TypedDict, total=False):
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]
    answer_subgraph_state: dict[str, Any]


class DraftGenerateInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    final_context: str
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]


class AnswerReviewCitationInput(TypedDict, total=False):
    loop_counts: LoopCounts
    draft_answer: str
    final_context: str


class AnswerReviewLLMInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    loop_counts: LoopCounts
    draft_answer: str
    final_context: str


class AnswerReviewFuseInput(TypedDict, total=False):
    loop_counts: LoopCounts
    answer_review_runs: list[AnswerReviewRun]
    reflection: ReflectionResult
    draft_answer: str
    stage_summaries: dict[str, Any]

class AnswerRepairInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    loop_counts: LoopCounts
    draft_answer: str
    final_context: str
    answer_subgraph_state: dict[str, Any]
    stage_summaries: dict[str, Any]


class AnswerCommitInput(TypedDict, total=False):
    reflection: ReflectionResult
    loop_counts: LoopCounts
    answer_subgraph_state: dict[str, Any]
    final_answer: str
    draft_answer: str
    best_answer: str
    best_answer_meta: dict[str, Any]
    stage_summaries: dict[str, Any]


class ForceExitInput(TypedDict, total=False):
    routing_decisions: dict[str, RoutingDecision]
    reflection: ReflectionResult
    loop_counts: LoopCounts
    final_answer: str
    draft_answer: str
    best_answer: str
    best_answer_meta: dict[str, Any]
    clarification_payload: ClarificationPayload
    stage_summaries: dict[str, Any]


def merge_routing_decision(
    state: dict[str, Any],
    phase: str,
    decision: RoutingDecision,
    *,
    updates: dict[str, Any] | None = None,
) -> dict[str, dict[str, RoutingDecision]]:
    """Merge a canonical routing record into state/update payloads."""

    merged: dict[str, RoutingDecision] = {}
    current = state.get("routing_decisions")
    if isinstance(current, dict):
        merged = {key: value for key, value in current.items() if isinstance(value, dict)}
    if isinstance(updates, dict):
        update_routing = updates.get("routing_decisions")
        if isinstance(update_routing, dict):
            merged = {
                **merged,
                **{
                    key: value
                    for key, value in update_routing.items()
                    if isinstance(value, dict)
                },
            }
    existing = merged.get(phase)
    if isinstance(existing, dict):
        merged[phase] = {**existing, **decision}
    else:
        merged[phase] = dict(decision)
    return {"routing_decisions": merged}


def resolve_routing_decision(state: dict[str, Any], phase: str) -> RoutingDecision:
    """Read a canonical routing record from state."""

    routing = state.get("routing_decisions")
    if not isinstance(routing, dict):
        return {}
    decision = routing.get(phase)
    if not isinstance(decision, dict):
        return {}
    return decision


_TERMINAL_ROUTING_PHASE_ORDER: tuple[str, ...] = (
    "answer_subgraph",
    "doc_gate",
    "preprocess",
)


def resolve_terminal_routing_decision(
    state: dict[str, Any],
    *,
    next_nodes: set[str] | None = None,
) -> tuple[str | None, RoutingDecision]:
    """Resolve the latest canonical terminal-control routing record."""

    for phase in _TERMINAL_ROUTING_PHASE_ORDER:
        decision = resolve_routing_decision(state, phase)
        next_node = str(decision.get("next_node") or "").strip()
        if not next_node:
            continue
        if next_nodes is not None and next_node not in next_nodes:
            continue
        return phase, decision
    return None, {}


def make_initial_state(
    *,
    user_input: str,
    messages: list[AnyMessage] | None = None,
) -> KbChatInternalState:
    """Create a minimal, serializable initial state for an agentic KB chat run."""

    return {
        "messages": messages or [],
        "user_input": user_input,
        "schema_version": STATE_SCHEMA_V3,
        "pending_tool_calls": [],
        "loop_counts": {
            "total_rounds": 0,
            "retrieval_retries": 0,
            "generation_retries": 0,
        },
        "stage_summaries": {},
        "metrics": {},
    }


def build_graph_input_state(state: dict[str, Any] | KbChatInputState) -> KbChatInputState:
    """Project arbitrary/internal state down to the public graph input schema."""

    messages = state.get("messages") if isinstance(state, dict) else None
    user_input = state.get("user_input") if isinstance(state, dict) else None
    return {
        "messages": messages if isinstance(messages, list) else [],
        "user_input": user_input if isinstance(user_input, str) else "",
    }
