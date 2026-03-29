"""Research observability / gate / fault helpers。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import httpx
from sqlalchemy.exc import OperationalError, TimeoutError as SATimeoutError

from app.core.settings import Settings
from app.models.research_session import ResearchSession
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_source_bundle import ResearchSourceBundle

try:  # pragma: no cover - 依赖在运行环境中存在，这里只做导入兜底
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError
except Exception:  # pragma: no cover
    class RedisError(Exception):
        pass

    class RedisConnectionError(RedisError):
        pass

    class RedisTimeoutError(RedisError):
        pass


@dataclass(slots=True, frozen=True)
class ResearchTraceLink:
    lc_agent_name: str
    namespace: str
    trace_id: str | None = None
    source_provider: str | None = None


@dataclass(slots=True, frozen=True)
class ResearchProviderStat:
    source_provider: str
    channel: str
    latency_ms: int | None = None
    success: bool = True
    status_code: int | None = None
    error_type: str | None = None


@dataclass(slots=True, frozen=True)
class ResearchModelStat:
    layer: str
    model: str
    lc_agent_name: str
    namespace: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(slots=True, frozen=True)
class ResearchRuntimeRunResult:
    source_bundle: ResearchSourceBundle
    trace_links: tuple[ResearchTraceLink, ...] = ()
    provider_stats: tuple[ResearchProviderStat, ...] = ()
    model_stats: tuple[ResearchModelStat, ...] = ()
    latency_ms: int | None = None
    total_cost_usd: float | None = None
    quality_score: float | None = None


@dataclass(slots=True, frozen=True)
class ResearchGateThresholds:
    min_quality_score: float = 0.75
    max_p95_ms: int = 120_000
    max_session_cost_usd: float = 2.0


def build_research_gate_thresholds(settings: Settings | None = None) -> ResearchGateThresholds:
    if settings is None:
        return ResearchGateThresholds()
    return ResearchGateThresholds(
        min_quality_score=float(settings.research_gate_min_quality_score),
        max_p95_ms=int(settings.research_gate_max_p95_ms),
        max_session_cost_usd=float(settings.research_gate_max_session_cost_usd),
    )


def ensure_research_trace_id(session: ResearchSession) -> str:
    if str(session.trace_id or "").strip():
        return str(session.trace_id)
    identity = session.id or session.thread_id
    session.trace_id = f"research:{identity}"
    return str(session.trace_id)


def build_trace_links(
    *,
    session: ResearchSession,
    runtime_result: ResearchRuntimeRunResult,
) -> list[dict[str, Any]]:
    trace_id = ensure_research_trace_id(session)
    deduped: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}

    def _remember(link: ResearchTraceLink) -> None:
        namespace = _normalize_namespace(link.namespace)
        lc_agent_name = str(link.lc_agent_name or "").strip() or "deep-research"
        resolved_trace_id = str(link.trace_id or trace_id)
        source_provider = (
            str(link.source_provider).strip() if link.source_provider is not None else None
        )
        key = (namespace, lc_agent_name, resolved_trace_id, source_provider)
        deduped[key] = {
            "trace_id": resolved_trace_id,
            "session_id": str(session.id),
            "thread_id": session.thread_id,
            "lc_agent_name": lc_agent_name,
            "namespace": namespace,
            "source_provider": source_provider,
        }

    _remember(
        ResearchTraceLink(
            lc_agent_name="deep-research",
            namespace="main",
            trace_id=trace_id,
        )
    )
    for item in runtime_result.trace_links:
        _remember(item)
    return list(deduped.values())


def build_research_metrics(
    *,
    session: ResearchSession,
    plan_snapshot: ResearchPlanSnapshot,
    runtime_result: ResearchRuntimeRunResult,
) -> dict[str, Any]:
    source_bundle = runtime_result.source_bundle
    trace_links = build_trace_links(session=session, runtime_result=runtime_result)
    quality_score = (
        float(runtime_result.quality_score)
        if runtime_result.quality_score is not None
        else _calculate_quality_score(
            plan_snapshot=plan_snapshot,
            citations=source_bundle.citations,
            findings=source_bundle.findings,
            coverage_gaps=source_bundle.coverage_gaps,
        )
    )

    metrics = {
        "trace": {
            "trace_id": ensure_research_trace_id(session),
            "session_id": str(session.id),
            "thread_id": session.thread_id,
            "links": trace_links,
        },
        "quality": {
            "score": quality_score,
            "citation_count": len(source_bundle.citations),
            "finding_count": len(source_bundle.findings),
            "coverage_gap_count": len(source_bundle.coverage_gaps),
            "target_sources": [item.value for item in plan_snapshot.target_sources],
            "channels": _build_channel_metrics(
                target_sources=plan_snapshot.target_sources,
                citations=source_bundle.citations,
            ),
        },
        "latency": _build_latency_metrics(
            session=session,
            runtime_latency_ms=runtime_result.latency_ms,
        ),
        "cost": _build_cost_metrics(runtime_result.model_stats, runtime_result.total_cost_usd),
        "providers": _build_provider_metrics(
            citations=source_bundle.citations,
            provider_stats=runtime_result.provider_stats,
            fallback_provider_counts=source_bundle.provider_counts,
        ),
        "models": _build_model_metrics(runtime_result.model_stats),
        "faults": {
            "records": [],
            "by_category": {},
            "by_source_provider": {},
        },
    }
    return metrics


def classify_research_fault(
    exc: Exception,
    *,
    source_provider: str | None = None,
) -> dict[str, Any]:
    category = "unknown"
    retryable = False
    status_code: int | None = None

    if isinstance(exc, (SATimeoutError, OperationalError)):
        category = "db_jitter"
        retryable = True
    elif isinstance(exc, (RedisConnectionError, RedisTimeoutError, RedisError)):
        category = "redis_unavailable"
        retryable = True
    elif isinstance(exc, httpx.HTTPStatusError):
        status_code = int(exc.response.status_code)
        if status_code == 429:
            category = "rate_limited"
            retryable = True
        else:
            category = "provider_http_error"
            retryable = status_code >= 500
    elif isinstance(exc, httpx.ConnectError):
        category = "instance_unreachable"
        retryable = True
    elif isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        category = "timeout"
        retryable = True
    elif isinstance(exc, (json.JSONDecodeError, ValueError, TypeError)):
        category = "malformed_response"

    return {
        "category": category,
        "source_provider": source_provider,
        "retryable": retryable,
        "status_code": status_code,
        "exception_type": exc.__class__.__name__,
        "message": str(exc),
    }


def build_failure_metrics(
    *,
    session: ResearchSession,
    fault: dict[str, Any],
    thresholds: ResearchGateThresholds,
    existing_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = dict(existing_metrics or {})
    trace_section = metrics.get("trace") if isinstance(metrics.get("trace"), dict) else {}
    metrics["trace"] = {
        "trace_id": ensure_research_trace_id(session),
        "session_id": str(session.id),
        "thread_id": session.thread_id,
        "links": trace_section.get("links")
        if isinstance(trace_section.get("links"), list)
        else [
            {
                "trace_id": ensure_research_trace_id(session),
                "session_id": str(session.id),
                "thread_id": session.thread_id,
                "lc_agent_name": "deep-research",
                "namespace": "main",
                "source_provider": None,
            }
        ],
    }
    metrics["quality"] = (
        metrics.get("quality") if isinstance(metrics.get("quality"), dict) else {"score": 0.0}
    )
    metrics["latency"] = _build_latency_metrics(session=session, runtime_latency_ms=None)
    metrics["cost"] = (
        metrics.get("cost")
        if isinstance(metrics.get("cost"), dict)
        else {"session_cost_usd": None, "by_layer": {}, "by_lc_agent_name": {}}
    )
    metrics["providers"] = (
        metrics.get("providers")
        if isinstance(metrics.get("providers"), dict)
        else {"by_source_provider": {}}
    )
    metrics["models"] = (
        metrics.get("models")
        if isinstance(metrics.get("models"), dict)
        else {"by_layer": {}, "by_lc_agent_name": {}}
    )

    existing_faults = metrics.get("faults") if isinstance(metrics.get("faults"), dict) else {}
    records = list(existing_faults.get("records") or [])
    records.append(dict(fault))
    metrics["faults"] = _build_fault_metrics(records)
    metrics["gate"] = evaluate_research_gate(metrics=metrics, thresholds=thresholds)
    return metrics


def evaluate_research_gate(
    *,
    metrics: dict[str, Any],
    thresholds: ResearchGateThresholds,
) -> dict[str, Any]:
    quality = _float_or_none((metrics.get("quality") or {}).get("score"))
    p95_ms = _int_or_none((metrics.get("latency") or {}).get("p95_ms"))
    session_cost_usd = _float_or_none((metrics.get("cost") or {}).get("session_cost_usd"))
    replay = metrics.get("replay") if isinstance(metrics.get("replay"), dict) else {}
    replay_pass = replay.get("pass")
    fault_records = (metrics.get("faults") or {}).get("records") or []

    violations: list[str] = []
    if quality is None:
        violations.append("quality_score_missing")
    elif quality < thresholds.min_quality_score:
        violations.append("quality_score")
    if p95_ms is None:
        violations.append("p95_ms_missing")
    elif p95_ms > thresholds.max_p95_ms:
        violations.append("p95_ms")
    if session_cost_usd is None:
        violations.append("session_cost_usd_missing")
    elif session_cost_usd > thresholds.max_session_cost_usd:
        violations.append("session_cost_usd")
    if replay_pass is False:
        violations.append("replay_consistency")
    if fault_records:
        violations.append("stability")

    return {
        "pass": len(violations) == 0,
        "violations": violations,
        "thresholds": {
            "quality_score": thresholds.min_quality_score,
            "p95_ms": thresholds.max_p95_ms,
            "session_cost_usd": thresholds.max_session_cost_usd,
        },
        "scores": {
            "quality_score": quality,
            "p95_ms": p95_ms,
            "session_cost_usd": session_cost_usd,
        },
    }


def _build_channel_metrics(
    *,
    target_sources: Sequence[ResearchSourceTarget],
    citations: Sequence[ResearchCanonicalCitation],
) -> dict[str, dict[str, Any]]:
    citation_counts = {
        "kb": 0,
        "web": 0,
        "paper": 0,
        "hybrid": 0,
    }
    for citation in citations:
        citation_counts[citation.source_type.value] = (
            citation_counts.get(citation.source_type.value, 0) + 1
        )
    citation_counts["hybrid"] = 1 if len({_citation_channel(item) for item in citations}) >= 2 else 0
    targeted = {item.value for item in target_sources}
    return {
        key: {
            "targeted": key in targeted,
            "citation_count": value,
        }
        for key, value in citation_counts.items()
    }


def _build_provider_metrics(
    *,
    citations: Sequence[ResearchCanonicalCitation],
    provider_stats: Sequence[ResearchProviderStat],
    fallback_provider_counts: dict[str, int],
) -> dict[str, Any]:
    aggregated: dict[str, dict[str, Any]] = {}
    for citation in citations:
        entry = aggregated.setdefault(
            citation.source_provider,
            {
                "count": 0,
                "success_count": 0,
                "failure_count": 0,
                "latency_ms_avg": None,
                "channels": set(),
            },
        )
        entry["channels"].add(_citation_channel(citation))

    for provider, count in fallback_provider_counts.items():
        entry = aggregated.setdefault(
            provider,
            {
                "count": 0,
                "success_count": 0,
                "failure_count": 0,
                "latency_ms_avg": None,
                "channels": set(),
            },
        )
        entry["count"] = max(int(entry["count"]), int(count))

    latency_totals: dict[str, int] = {}
    latency_counts: dict[str, int] = {}
    stat_counts: dict[str, int] = {}
    for stat in provider_stats:
        entry = aggregated.setdefault(
            stat.source_provider,
            {
                "count": 0,
                "success_count": 0,
                "failure_count": 0,
                "latency_ms_avg": None,
                "channels": set(),
            },
        )
        stat_counts[stat.source_provider] = stat_counts.get(stat.source_provider, 0) + 1
        entry["channels"].add(str(stat.channel))
        if stat.success:
            entry["success_count"] += 1
        else:
            entry["failure_count"] += 1
        if stat.latency_ms is not None:
            latency_totals[stat.source_provider] = latency_totals.get(stat.source_provider, 0) + int(
                stat.latency_ms
            )
            latency_counts[stat.source_provider] = latency_counts.get(stat.source_provider, 0) + 1

    for provider, entry in aggregated.items():
        if stat_counts.get(provider):
            entry["count"] = max(int(entry["count"]), stat_counts[provider])
        if latency_counts.get(provider):
            entry["latency_ms_avg"] = round(
                latency_totals[provider] / latency_counts[provider]
            )
        entry["channels"] = sorted(entry["channels"])
    return {"by_source_provider": aggregated}


def _build_model_metrics(model_stats: Sequence[ResearchModelStat]) -> dict[str, Any]:
    by_layer: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}
    for stat in model_stats:
        cost_value = round(float(stat.cost_usd or 0.0), 6)
        layer_entry = by_layer.setdefault(
            stat.layer,
            {"count": 0, "cost_usd": 0.0, "models": set()},
        )
        layer_entry["count"] += 1
        layer_entry["cost_usd"] = round(layer_entry["cost_usd"] + cost_value, 6)
        layer_entry["models"].add(stat.model)

        agent_entry = by_agent.setdefault(
            stat.lc_agent_name,
            {"count": 0, "cost_usd": 0.0, "namespaces": set(), "models": set()},
        )
        agent_entry["count"] += 1
        agent_entry["cost_usd"] = round(agent_entry["cost_usd"] + cost_value, 6)
        agent_entry["namespaces"].add(_normalize_namespace(stat.namespace))
        agent_entry["models"].add(stat.model)

    for entry in by_layer.values():
        entry["models"] = sorted(entry["models"])
    for entry in by_agent.values():
        entry["models"] = sorted(entry["models"])
        entry["namespaces"] = sorted(entry["namespaces"])
    return {
        "by_layer": by_layer,
        "by_lc_agent_name": by_agent,
    }


def _build_cost_metrics(
    model_stats: Sequence[ResearchModelStat],
    total_cost_usd: float | None,
) -> dict[str, Any]:
    model_metrics = _build_model_metrics(model_stats)
    resolved_total = (
        round(float(total_cost_usd), 6)
        if total_cost_usd is not None
        else round(sum(float(item.cost_usd or 0.0) for item in model_stats), 6)
    )
    return {
        "session_cost_usd": resolved_total,
        "by_layer": {
            key: {"cost_usd": value["cost_usd"], "count": value["count"]}
            for key, value in model_metrics["by_layer"].items()
        },
        "by_lc_agent_name": {
            key: {"cost_usd": value["cost_usd"], "count": value["count"]}
            for key, value in model_metrics["by_lc_agent_name"].items()
        },
    }


def _build_latency_metrics(
    *,
    session: ResearchSession,
    runtime_latency_ms: int | None,
) -> dict[str, Any]:
    session_latency_ms = _duration_ms(session.started_at, session.finished_at)
    resolved_runtime_latency_ms = (
        int(runtime_latency_ms)
        if runtime_latency_ms is not None
        else session_latency_ms
    )
    p95_ms = resolved_runtime_latency_ms if resolved_runtime_latency_ms is not None else session_latency_ms
    return {
        "runtime_latency_ms": resolved_runtime_latency_ms,
        "session_latency_ms": session_latency_ms,
        "p95_ms": p95_ms,
    }


def _build_fault_metrics(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, int]] = {}
    by_source_provider: dict[str, dict[str, int]] = {}
    normalized_records: list[dict[str, Any]] = []
    for item in records:
        record = dict(item)
        normalized_records.append(record)
        category = str(record.get("category") or "unknown")
        provider = record.get("source_provider")
        by_category.setdefault(category, {"count": 0})["count"] += 1
        if provider:
            by_source_provider.setdefault(str(provider), {"count": 0})["count"] += 1
    return {
        "records": normalized_records,
        "by_category": by_category,
        "by_source_provider": by_source_provider,
    }


def _calculate_quality_score(
    *,
    plan_snapshot: ResearchPlanSnapshot,
    citations: Sequence[ResearchCanonicalCitation],
    findings: Sequence[str],
    coverage_gaps: Sequence[str],
) -> float:
    citation_component = min(0.35, 0.175 * len(citations))
    finding_component = min(0.25, 0.125 * len(findings))
    coverage_component = max(0.0, 0.2 - 0.1 * len(coverage_gaps))
    target_coverage_component = 0.2 * _target_source_coverage_ratio(
        target_sources=plan_snapshot.target_sources,
        citations=citations,
    )
    return round(
        citation_component + finding_component + coverage_component + target_coverage_component,
        4,
    )


def _target_source_coverage_ratio(
    *,
    target_sources: Sequence[ResearchSourceTarget],
    citations: Sequence[ResearchCanonicalCitation],
) -> float:
    if not target_sources:
        return 0.0
    covered_channels = {_citation_channel(item) for item in citations}

    def _covered(target: ResearchSourceTarget) -> bool:
        if target == ResearchSourceTarget.HYBRID:
            return len(covered_channels.intersection({"kb", "web", "paper"})) >= 2
        return target.value in covered_channels

    covered_count = sum(1 for item in target_sources if _covered(item))
    return covered_count / len(target_sources)


def _citation_channel(citation: ResearchCanonicalCitation) -> str:
    if citation.source_type == ResearchSourceType.KB:
        return "kb"
    if citation.source_type == ResearchSourceType.PAPER:
        return "paper"
    return "web"


def _normalize_namespace(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized or "main"


def _duration_ms(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> int | None:
    if started_at is None or finished_at is None:
        return None
    delta = finished_at - started_at
    return max(int(delta.total_seconds() * 1000), 0)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
