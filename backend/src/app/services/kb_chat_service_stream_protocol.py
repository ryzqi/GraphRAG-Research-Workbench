from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any


from app.models.agent_run import AgentRunStatus
from app.schemas.chats import (
    EvidenceItem,
)
from app.services.evidence_guardrails import (
    is_kb_refusal_answer,
    is_stable_citation_id,
)
from app.services.streaming import (
    extract_answer_text,
)
from app.agents.kb_chat_contracts import (
    validate_event_envelope_v2,
)

from app.services.kb_chat_service_contracts import (
    _KbChatStreamRunState,
    _STREAM_EVENT_VERSION,
    _as_str_dict,
)

logger = logging.getLogger(__name__)
def _semantic_cache_entry_admission_reason(self, 
    *,
    status: AgentRunStatus | str,
    clarification_payload: dict[str, Any] | None,
    routing_decisions: dict[str, Any] | None,
    reflection: dict[str, Any] | None,
    degrade_reason: str | None,
    answer: str,
    evidence: list[EvidenceItem],
    metrics: dict[str, Any] | None,
    stage_summaries: dict[str, Any] | None,
) -> str | None:
    status_value = getattr(status, "value", status)
    if str(status_value or "").strip() != AgentRunStatus.SUCCEEDED.value:
        return "status_not_succeeded"
    reason = self._resolve_terminal_reason(
        clarification_payload=clarification_payload,
        routing_decisions=routing_decisions,
        reflection=reflection,
        degrade_reason=degrade_reason,
    )
    if reason in {"clarify", "severe_conflict", "conflict_retry_exhausted"}:
        return reason
    if is_kb_refusal_answer(extract_answer_text(answer)):
        return "refusal_answer"
    if not isinstance(evidence, list) or not evidence:
        return "missing_evidence"
    raw_citation_ids = (
        metrics.get("citation_ids") if isinstance(metrics, dict) else None
    )
    citation_ids = (
        [
            str(item).strip().upper()
            for item in raw_citation_ids
            if isinstance(item, str)
            and is_stable_citation_id(str(item).strip().upper())
        ]
        if isinstance(raw_citation_ids, list)
        else []
    )
    if not citation_ids:
        return "missing_citation_ids"
    evidence_fingerprint = self._semantic_cache_evidence_fingerprint(
        evidence
    )
    if not evidence_fingerprint:
        return "missing_evidence_fingerprint"
    answer_review_summary = (
        stage_summaries.get("answer_review")
        if isinstance(stage_summaries, dict)
        else None
    )
    if not (
        isinstance(answer_review_summary, dict)
        and answer_review_summary.get("passed") is True
    ):
        return "answer_review_not_passed"
    return None

def _calculate_stream_progress(self, 
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

def _shorten_stream_text(self, value: object, limit: int = 120) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."

def _build_node_io_summary(self, 
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
            "answer_review": "answer_review",
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

    if node == "query_plan" and isinstance(node_summary, dict):
        for key, value in (
            ("strategy", node_summary.get("strategy")),
            ("confidence", node_summary.get("confidence")),
            ("next_node", node_summary.get("next_node")),
            ("recall_risk", node_summary.get("recall_risk")),
        ):
            if value is not None:
                io_summary[key] = value

    if node == "query_plan_finalize" and isinstance(node_summary, dict):
        for key, value in (
            ("query_count", node_summary.get("query_count")),
            ("candidate_count", node_summary.get("candidate_count")),
            ("selected_count", node_summary.get("selected_count")),
            ("fallback_reason", node_summary.get("fallback_reason")),
            ("rejection_counts", node_summary.get("rejection_counts")),
            ("kind_breakdown", node_summary.get("kind_breakdown")),
        ):
            if value is not None:
                io_summary[key] = value

        query_items = update.get("query_items")
        if isinstance(query_items, list):
            io_summary["query_bundle_items_count"] = len(query_items)
            io_summary["query_count"] = len(query_items)

    if node in {"resolve_reference", "query_normalize", "transform_query"}:
        query = (
            update.get("normalized_query")
            or update.get("resolved_query")
            or update.get("coref_query")
        )
        if isinstance(query, str) and query.strip():
            io_summary["query"] = self._shorten_stream_text(query, 160)

    if node in {"decomposition", "generate_variants"}:
        list_key = "sub_queries" if node == "decomposition" else "multi_queries"
        values = update.get(list_key)
        if isinstance(values, list):
            io_summary["query_count"] = len(
                [v for v in values if isinstance(v, str)]
            )

    if node == "hyde":
        hyde_docs = update.get("hyde_docs")
        if isinstance(hyde_docs, list):
            io_summary["hyde_docs_count"] = len(
                [doc for doc in hyde_docs if isinstance(doc, str) and doc.strip()]
            )

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
            io_summary["draft_preview"] = self._shorten_stream_text(
                draft_answer, 180
            )

    if node in {"ambiguity_check", "answer_subgraph", "force_exit"}:
        final_answer = update.get("final_answer")
        if isinstance(final_answer, str) and final_answer.strip():
            io_summary["final_preview"] = self._shorten_stream_text(
                final_answer, 180
            )

    if node == "answer_review_fuse":
        best_answer = update.get("best_answer")
        if isinstance(best_answer, str) and best_answer.strip():
            io_summary["best_answer_preview"] = self._shorten_stream_text(
                best_answer, 120
            )

    if node == "answer_subgraph":
        answer_summary = node_summary if isinstance(node_summary, dict) else {}
        routing = _as_str_dict(update.get("routing_decisions"))
        answer_route = _as_str_dict(routing.get("answer_subgraph"))
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

def _build_stream_state_payload(self, 
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
        else stage_status.get(current_step_id)
        if current_step_id
        else None
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
        "progress": self._calculate_stream_progress(
            stage_status=stage_status, run_status=run_status
        ),
        "ts": datetime.now(timezone.utc).isoformat(),
    }

def _build_protocol_event_payload(self, 
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

def _build_node_io_payload(self, 
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
    return self._build_protocol_event_payload(
        event_type="node_io",
        run_id=run_id,
        payload=payload,
        node={"id": node_id, "name": node_name},
        node_path=node_path,
    )

def _json_safe_custom_payload(self, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        import json

        return json.loads(json.dumps(value, default=str))
    except Exception:
        return None

def _build_graph_stream_options(self, ) -> dict[str, Any]:
    return {
        "stream_mode": ["messages", "updates", "custom", "tasks"],
        "subgraphs": True,
        "version": "v2",
    }

def _build_step_payload_from_task_event(self, 
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

def _normalize_graph_stream_event(self, 
    event: Any,
) -> tuple[str, Any, list[str] | None] | None:
    """规范化 LangGraph v2 StreamPart 或旧版 tuple 流输出。"""

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

def _normalize_stream_namespace(self, node_path: list[str] | None) -> tuple[str, ...]:
    if not isinstance(node_path, list):
        return ()
    return tuple(str(item) for item in node_path if isinstance(item, str) and item)

def _build_stream_execution_scope(self, 
    *,
    node_name: str | None,
    node_path: list[str] | None = None,
) -> tuple[tuple[str, ...], str] | None:
    if not isinstance(node_name, str) or not node_name:
        return None
    return (self._normalize_stream_namespace(node_path), node_name)

def _remember_stream_execution(self, 
    *,
    stream_state: _KbChatStreamRunState,
    execution_id: str | None,
    node_name: str | None,
    node_path: list[str] | None = None,
) -> None:
    if not isinstance(execution_id, str) or not execution_id:
        return
    scope = self._build_stream_execution_scope(
        node_name=node_name,
        node_path=node_path,
    )
    if scope is None:
        return
    stream_state.latest_execution_by_scope[scope] = execution_id

def _resolve_stream_execution_id(self, 
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
    scope = self._build_stream_execution_scope(
        node_name=node_name,
        node_path=node_path,
    )
    if scope is None:
        return None
    return stream_state.latest_execution_by_scope.get(scope)

def _build_scoped_node_path(self, 
    *,
    node_name: str | None,
    node_path: list[str] | None = None,
) -> list[str]:
    scoped_path = list(self._normalize_stream_namespace(node_path))
    if isinstance(node_name, str) and node_name:
        if not scoped_path or scoped_path[-1] != node_name:
            scoped_path.append(node_name)
    return scoped_path

def _build_active_path(self, 
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

def _resolve_stream_state_node_name(self, 
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

def _apply_stream_state_node_io(self, 
    *,
    stream_state: _KbChatStreamRunState,
    payload: dict[str, Any],
    node_path: list[str] | None = None,
) -> str | None:
    node_name = self._resolve_stream_state_node_name(
        payload=payload,
        node_path=node_path,
    )
    phase = payload.get("phase")
    if node_name is None or phase not in {"start", "end", "error"}:
        return None

    raw_attempt = self._safe_non_negative_int(payload.get("attempt"))
    attempt = (
        raw_attempt if isinstance(raw_attempt, int) and raw_attempt > 0 else None
    )
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

def _apply_stream_state_step(self, 
    *,
    stream_state: _KbChatStreamRunState,
    payload: dict[str, Any],
    node_path: list[str] | None = None,
) -> str | None:
    node_name = payload.get("node") or payload.get("step_id")
    status = payload.get("status")
    if (
        not isinstance(node_name, str)
        or not node_name
        or not isinstance(status, str)
    ):
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
    self._remember_stream_execution(
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

def _safe_non_negative_int(self, value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    return None