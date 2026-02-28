"""KB Chat v3 contracts for state, routing, and stream envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, TypedDict

EVENT_ENVELOPE_V2 = "event_envelope_v2"
STATE_SCHEMA_V3 = "kb_chat_state_v3"

NodeScopedEventType = Literal[
    "messages",
    "updates",
    "node_io",
    "ui_event",
    "final",
    "error",
    "interrupt",
]

NODE_SCOPED_EVENT_TYPES: set[str] = {
    "messages",
    "updates",
    "node_io",
}


class ContractViolationError(ValueError):
    """Raised when contract validation fails."""


class PlanState(TypedDict, total=False):
    """Planning layer state: intent and query planning artifacts."""

    schema_version: str
    user_input: str
    context_frame: dict[str, Any]
    rewrite_plan: dict[str, Any]
    decomposition_plan: dict[str, Any]
    message_plan: dict[str, Any]
    query_bundle: dict[str, Any]
    retrieval_plan: dict[str, Any]
    query_strategy: str
    query_strategy_confidence: float
    query_strategy_signals: list[str]


class ExecutionState(TypedDict, total=False):
    """Execution layer state: runtime progression and retrieval/answer artifacts."""

    schema_version: str
    messages: list[Any]
    loop_counts: dict[str, Any]
    final_context: str
    draft_answer: str
    final_answer: str
    best_answer: str
    best_answer_meta: dict[str, Any]
    reflection: dict[str, Any]
    clarification_payload: dict[str, Any]
    doc_gate_state: dict[str, Any]


class ObservabilityState(TypedDict, total=False):
    """Observability layer state: diagnostics and trace-oriented fields."""

    schema_version: str
    metrics: dict[str, Any]
    stage_summaries: dict[str, Any]
    answer_review_runs: list[dict[str, Any]]
    rewrite_branch_runs: list[dict[str, Any]]
    subquery_runs: list[dict[str, Any]]
    degrade_reason: str


@dataclass(frozen=True)
class StateFieldContract:
    layer: Literal["plan", "execution", "observability"]
    writers: tuple[str, ...]
    lifecycle: Literal["init", "loop", "terminal"]


STATE_FIELD_CONTRACTS: dict[str, StateFieldContract] = {
    "rewrite_plan": StateFieldContract("plan", ("rewrite_query",), "loop"),
    "decomposition_plan": StateFieldContract(
        "plan", ("decomposition", "generate_variants"), "loop"
    ),
    "retrieval_plan": StateFieldContract(
        "plan", ("prepare_messages", "merge_retrieval_results"), "loop"
    ),
    "messages": StateFieldContract("execution", ("graph_runtime",), "loop"),
    "final_context": StateFieldContract("execution", ("merge_retrieval_results",), "loop"),
    "reflection": StateFieldContract(
        "execution", ("doc_grader_llm", "answer_review_fuse"), "loop"
    ),
    "final_answer": StateFieldContract("execution", ("answer_commit",), "terminal"),
    "stage_summaries": StateFieldContract("observability", ("graph_runtime",), "loop"),
    "metrics": StateFieldContract("observability", ("graph_runtime",), "loop"),
    "degrade_reason": StateFieldContract("observability", ("route_after_doc_grader",), "loop"),
}


@dataclass(frozen=True)
class RouteTruthRow:
    source: str
    condition: str
    destination: Literal[
        "clarify",
        "retrieval_subgraph",
        "transform_query",
        "finalize",
        "force_exit",
    ]
    side_effects: tuple[str, ...]


ROUTING_TRUTH_TABLE: tuple[RouteTruthRow, ...] = (
    RouteTruthRow(
        source="preprocess_subgraph",
        condition="clarify needed",
        destination="clarify",
        side_effects=("emit_interrupt", "persist_pending_payload"),
    ),
    RouteTruthRow(
        source="preprocess_subgraph",
        condition="ready",
        destination="retrieval_subgraph",
        side_effects=("write_selected_query_plan",),
    ),
    RouteTruthRow(
        source="retrieval_subgraph",
        condition="evidence empty and retrieval_retry_budget>0",
        destination="transform_query",
        side_effects=("increment_retrieval_retry",),
    ),
    RouteTruthRow(
        source="evidence_gate_subgraph",
        condition="pass",
        destination="finalize",
        side_effects=("write_gate_decision", "commit_final_answer"),
    ),
    RouteTruthRow(
        source="evidence_gate_subgraph",
        condition="retryable fail",
        destination="transform_query",
        side_effects=("set_degrade_hint",),
    ),
    RouteTruthRow(
        source="evidence_gate_subgraph",
        condition="non-retryable fail",
        destination="force_exit",
        side_effects=("set_final_reason",),
    ),
    RouteTruthRow(
        source="answer_subgraph",
        condition="review pass",
        destination="finalize",
        side_effects=("commit_final_answer",),
    ),
    RouteTruthRow(
        source="answer_subgraph",
        condition="review fail and retry budget>0",
        destination="transform_query",
        side_effects=("set_retry_advice",),
    ),
    RouteTruthRow(
        source="answer_subgraph",
        condition="review fail and no budget",
        destination="force_exit",
        side_effects=("fallback_to_best_candidate",),
    ),
)


def detect_event_protocol_version(event: Mapping[str, Any]) -> str:
    version = event.get("version")
    if version == EVENT_ENVELOPE_V2:
        return "v2"
    if isinstance(version, str) and version.startswith("2"):
        return "v2"
    if "event_id" in event and "seq" in event:
        return "v2"
    return "v2"


def validate_state_write_access(*, field: str, writer: str) -> None:
    contract = STATE_FIELD_CONTRACTS.get(field)
    if contract is None:
        return
    if writer not in contract.writers:
        allowed = ", ".join(contract.writers)
        raise ContractViolationError(
            f"state field '{field}' is owned by [{allowed}], got '{writer}'"
        )


def validate_event_envelope_v2(event: Mapping[str, Any]) -> None:
    required = ("version", "type", "event_id", "seq", "ts", "run", "attempt", "node_path")
    for key in required:
        if key not in event:
            raise ContractViolationError(f"missing required envelope field: {key}")

    if event.get("version") not in {EVENT_ENVELOPE_V2, "2", "2.0"}:
        raise ContractViolationError("invalid envelope version for v2 payload")
    if not isinstance(event.get("run"), Mapping) or not event["run"].get("id"):
        raise ContractViolationError("missing required envelope field: run.id")
    if not isinstance(event.get("node_path"), list):
        raise ContractViolationError("invalid envelope field: node_path must be an array")

    event_type = event.get("type")
    if isinstance(event_type, str) and event_type in NODE_SCOPED_EVENT_TYPES:
        node = event.get("node")
        if not isinstance(node, Mapping):
            raise ContractViolationError("missing required envelope field: node")
        if not node.get("id"):
            raise ContractViolationError("missing required envelope field: node.id")
        if not node.get("name"):
            raise ContractViolationError("missing required envelope field: node.name")
