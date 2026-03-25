"""KB Chat agentic 图状态：结构化且兼容 checkpointer。"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.agents.kb_chat_contracts import STATE_SCHEMA_V3

# 查询包类型

from app.schemas.query_enhancement import QueryItem


# 反思 / 预算 / 指标

ReflectionAction = Literal["none", "clarify", "transform_query", "force_exit"]
ComplexityLevel = Literal["simple", "moderate", "complex"]


class ReflectionResult(TypedDict, total=False):
    """反思层评分结果，可序列化。"""

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
    """跨节点 / 子图决策使用的规范路由记录。"""

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
    """用于预算控制的循环计数。"""

    total_rounds: int
    retrieval_retries: int
    generation_retries: int


class ContextTurn(TypedDict):
    """用于展示或调试的近期对话轮次。"""

    role: Literal["user", "assistant"]
    text: str


class ContextFrame(TypedDict, total=False):
    """改写 / 检索前组装的结构化上下文。"""

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
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
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
    missing_citations: list[str]
    invalid_citations: list[str]
    unsupported_claims: list[str]
    affected_paragraph_ids: list[str]
    details: dict[str, object]
    fallback_reason: str | None
    decision_source: str
    latency_ms: int


# 图状态 schema

class KbChatInputState(TypedDict):
    """单轮 KB Chat 的最小公开输入。"""

    # 注意：LangGraph 为消息列表提供了专用 reducer。
    messages: Annotated[list[AnyMessage], add_messages]

    # 原始用户问题，不做改写。
    user_input: str


class KbChatOutputState(TypedDict, total=False):
    """暴露给服务调用方的最小公开输出。"""

    final_answer: str
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]
    clarification_payload: ClarificationPayload
    stage_summaries: dict[str, Any]


class KbChatInternalStateBase(KbChatInputState):
    """agentic KB Chat 运行所需的内部字段。"""

    schema_version: str

    # 保持与现有 streaming/service 链路兼容。
    pending_tool_calls: list[dict]

    # 预算 / 可观测字段，保持与现有 AgentRun 字段兼容。
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]
    metrics: dict[str, Any]


class KbChatInternalState(KbChatInternalStateBase, total=False):
    """各阶段逐步补充的可选字段。

    阶段 I/O（高层说明，用于约束实现边界）：
    - MergeContext：读取 messages / user_input / memory_keys，写入
      context_frame / rewrite_input_query / merged_context
    - ResolveReference：读取 rewrite_input_query / context_frame，写入
      resolved_query / reference_resolution_meta
    - AmbiguityCheck：读取 resolved_query / normalized_query，写入 reflection / action（clarify）
    - QueryNormalize：读取 resolved_query，写入 normalized_query
    - QueryPlan：读取 normalized_query，写入 query_strategy，并路由到恢复后的增强节点
    - QueryPlanFinalize：读取查询族产物，写入
      query_plan_result / query_plan_diagnostics / query_items
    - RetrievalLayer：读取查询族信息，写入 final_context / metrics
    - ReflectionLayer：读取 final_context，写入 reflection（以及可选的改写查询）
    - AnswerSubgraph：读取 final_context，写入 draft_answer / final_answer / review
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
    query_plan_result: QueryPlanResult
    query_plan_diagnostics: QueryPlanDiagnostics
    retrieval_plan: RetrievalPlan
    retrieval_budget: dict[str, Any]
    retrieval_diagnostics: dict[str, float]
    query_items: list[QueryItem]
    subquery_runs: Annotated[list[SubqueryRun], add]
    subquery_task: dict[str, Any]

    final_context: str
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
    compression_stats: dict[str, Any]
    draft_answer: str
    final_answer: str
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]
    best_answer: str
    best_answer_meta: dict[str, Any]
    answer_subgraph_state: dict[str, Any]
    degrade_reason: str
    clarification_payload: ClarificationPayload

    answer_review_runs: Annotated[list[AnswerReviewRun], add]
    reflection: ReflectionResult
    routing_decisions: dict[str, RoutingDecision]


class KbChatEmptyState(TypedDict, total=False):
    """供忽略图状态的节点使用的显式空读侧 schema。"""


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
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
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
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]
    loop_counts: LoopCounts
    stage_summaries: dict[str, Any]


class AnswerReviewCitationInput(TypedDict, total=False):
    loop_counts: LoopCounts
    draft_answer: str
    final_context: str
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]


class AnswerReviewInput(TypedDict, total=False):
    user_input: str
    rewrite_input_query: str
    resolved_query: str
    coref_query: str
    normalized_query: str
    loop_counts: LoopCounts
    draft_answer: str
    final_context: str
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]


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
    evidence_items: list[dict[str, Any]]
    citation_catalog: dict[str, dict[str, Any]]
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]
    answer_subgraph_state: dict[str, Any]
    stage_summaries: dict[str, Any]


class AnswerCommitInput(TypedDict, total=False):
    reflection: ReflectionResult
    loop_counts: LoopCounts
    answer_subgraph_state: dict[str, Any]
    final_answer: str
    draft_answer: str
    answer_paragraphs: list[dict[str, Any]]
    answer_render_meta: dict[str, Any]
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
    """将规范路由记录合并到 state / updates 载荷。"""

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
    """从 state 中读取规范路由记录。"""

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
    """解析最新的规范终止控制路由记录。"""

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
    """为一次 agentic KB Chat 运行创建最小可序列化初始状态。"""

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
    """将任意 / 内部状态投影为公开图输入 schema。"""

    messages = state.get("messages") if isinstance(state, dict) else None
    user_input = state.get("user_input") if isinstance(state, dict) else None
    return {
        "messages": messages if isinstance(messages, list) else [],
        "user_input": user_input if isinstance(user_input, str) else "",
    }
