from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.agents.kb_chat_agentic.json_safety import ensure_json_safe
from app.core.errors import bad_request
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType
from app.schemas.chats import (
    KbChatConfig,
)
from app.api.sse import SseHeartbeatStats
from app.services.streaming import (
    StreamState,
)
from app.agents.kb_chat_agentic_state import (
    resolve_terminal_routing_decision,
)

from app.services.kb_chat_service_contracts import (
    _GRAY_CLARIFICATION_THRESHOLD,
    _GRAY_FINAL_THRESHOLD,
    _GRAY_P95_THRESHOLD,
    _GRAY_ROUTE_THRESHOLD,
    _KbChatExecution,
    _as_str_dict,
    _gray_release_log_dir,
)

logger = logging.getLogger(__name__)
def _ensure_no_pending_tool_approval(self, 
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

def _build_retrieval_stage_summary(self, 
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

def _safe_percent(self, value: float | int | None) -> float | None:
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

def _safe_rate(self, value: float | int | None) -> float:
    percent = self._safe_percent(value)
    return 100.0 if percent is None else percent

def _extract_run_latency_ms(self, metrics: dict[str, Any]) -> int | None:
    value = metrics.get("latency_ms")
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None

def _calc_percentile(self, values: list[int], p: float) -> float:
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
    window_size = int(
        getattr(self._settings, "kb_chat_gray_release_window_size", 200)
    )
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

def _compute_route_consistency(self, 
    *,
    query_strategy: str | None,
    routing_decisions: dict[str, Any] | None,
) -> float:
    checks: list[bool] = []
    if isinstance(query_strategy, str) and query_strategy:
        checks.append(query_strategy in {"direct", "decomposition", "multi_query"})
    routing = routing_decisions if isinstance(routing_decisions, dict) else {}
    answer_subgraph = (
        routing.get("answer_subgraph")
        if isinstance(routing.get("answer_subgraph"), dict)
        else {}
    )
    if answer_subgraph:
        checks.append(
            str(answer_subgraph.get("next_node") or "")
            in {"END", "transform_query", "force_exit"}
        )
    if not checks:
        return 100.0
    return round((sum(1 for ok in checks if ok) / len(checks)) * 100.0, 4)

def _compute_final_state_consistency(self, 
    *,
    routing_decisions: dict[str, Any] | None,
    terminal_reason: str | None,
) -> float:
    routing = routing_decisions if isinstance(routing_decisions, dict) else {}
    answer_subgraph = _as_str_dict(routing.get("answer_subgraph"))
    terminal_phase, terminal_route = resolve_terminal_routing_decision(
        {"routing_decisions": routing},
        next_nodes={"force_exit"},
    )
    next_step = str(answer_subgraph.get("next_node") or "")
    has_force_exit = isinstance(terminal_reason, str) and bool(
        terminal_reason.strip()
    )
    if not next_step and not has_force_exit:
        return 100.0
    if next_step == "END":
        return 100.0 if not has_force_exit else 0.0
    if next_step in {"transform_query", "force_exit"}:
        return 100.0 if has_force_exit else 0.0
    if terminal_phase == "preprocess" and terminal_route:
        return 100.0 if has_force_exit else 0.0
    return 0.0

def _compute_clarification_consistency(self, 
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

def _build_gray_release_gate(self, metrics: dict[str, Any]) -> dict[str, Any]:
    route = self._safe_rate(metrics.get("route_consistency_rate"))
    final = self._safe_rate(metrics.get("final_state_consistency_rate"))
    clarification = self._safe_rate(
        metrics.get("clarification_consistency_rate")
    )
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
    route_consistency_rate = (
        self._safe_rate(metric_values.get("route_consistency_rate")) or 100.0
    )
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
        "clarification_consistency_rate": metrics.get(
            "clarification_consistency_rate"
        ),
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

def _build_retry_cache_metrics(self, 
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

def _build_protocol_metrics(self, 
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
        heartbeat_stats.sent_count
        if isinstance(heartbeat_stats, SseHeartbeatStats)
        else 0
    )
    heartbeat_gaps = (
        heartbeat_stats.gap_ms_samples
        if isinstance(heartbeat_stats, SseHeartbeatStats)
        else []
    )
    heartbeat_gap_ms_p95 = round(
        self._calc_percentile(heartbeat_gaps, 0.95),
        4,
    )
    protocol_drift_rate = (
        round((drift_count / emit_total) * 100.0, 4) if emit_total > 0 else 0.0
    )
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

def _apply_guardrail_metrics(self, 
    *,
    metrics: dict[str, Any],
    stage_summaries: dict[str, Any],
    kb_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guardrails = _as_str_dict(metrics.get("guardrails"))
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
        else (
            exec_ctx.state.get("metrics")
            if isinstance(exec_ctx.state, dict)
            else {}
        )
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