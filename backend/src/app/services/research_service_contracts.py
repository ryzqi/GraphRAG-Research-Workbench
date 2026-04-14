from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models.research_artifact import ResearchArtifact
from app.models.research_event import ResearchEvent
from app.models.research_session import ResearchSession
from app.schemas.research import (
    ResearchArtifactRead,
    ResearchArtifactsResponse,
    ResearchCanonicalCitation,
    ResearchEventEnvelope,
    ResearchPlanSnapshot,
)
from app.services.research_artifact_store import normalize_optional_artifact_text
from app.services.research_presentation_snapshot import (
    build_research_presentation_snapshot,
)

_RUNTIME_PLAN_STEP_TODO_PATTERN = re.compile(r"^\[plan-step-(\d+)\]\s*")

def build_event_envelopes(
    session: ResearchSession,
    *,
    after_event_id: str | None = None,
) -> list[ResearchEventEnvelope]:
    events = sorted(session.events, key=lambda item: item.sequence)
    after_sequence = 0
    if after_event_id is not None:
        matched = next(
            (item for item in events if item.event_id == after_event_id), None
        )
        if matched is not None:
            after_sequence = matched.sequence
    return [
        build_event_envelope(session=session, event=event)
        for event in events
        if event.sequence > after_sequence
    ]

def build_artifacts_response(
    *,
    session: ResearchSession,
    events: list[ResearchEventEnvelope],
) -> ResearchArtifactsResponse:
    items = [
        ResearchArtifactRead(
            artifact_key=artifact.artifact_key,
            content_text=normalize_optional_artifact_text(artifact.content_text),
            content_json=artifact.content_json,
            citations=extract_artifact_citations(artifact),
            source_provider=normalize_optional_artifact_text(
                artifact.source_provider
            ),
            retrieval_method=normalize_optional_artifact_text(
                artifact.retrieval_method
            ),
            origin_url=normalize_optional_artifact_text(artifact.origin_url),
        )
        for artifact in sorted(
            session.artifacts, key=lambda item: item.artifact_key
        )
    ]
    items.append(
        ResearchArtifactRead(
            artifact_key="presentation_snapshot",
            content_json=build_research_presentation_snapshot(
                session=session,
                events=events,
                artifacts=items,
            ),
            citations=[],
        )
    )
    return ResearchArtifactsResponse(
        session_id=session.id,
        status=session.status,
        items=items,
    )

def extract_artifact_citations(
    artifact: ResearchArtifact,
) -> list[ResearchCanonicalCitation]:
    payload = artifact.content_json
    if not isinstance(payload, dict):
        return []
    raw_citations = payload.get("citations")
    if not isinstance(raw_citations, list):
        return []
    return [
        ResearchCanonicalCitation.model_validate(item)
        for item in raw_citations
        if isinstance(item, dict)
    ]

def plan_progress_updated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def normalize_plan_progress_index(
    value: object,
    *,
    total_steps: int,
) -> int | None:
    if not isinstance(value, int):
        return None
    if value < 1 or value > total_steps:
        return None
    return value

def extract_plan_progress_position(
    payload: dict[str, object] | None,
    *,
    total_steps: int,
) -> tuple[int | None, int]:
    if payload is None:
        return (1 if total_steps > 0 else None, 0)

    raw_completed = payload.get("completed_step_count")
    completed = raw_completed if isinstance(raw_completed, int) else 0
    completed = max(0, min(completed, total_steps))

    current = normalize_plan_progress_index(
        payload.get("current_step_index"),
        total_steps=total_steps,
    )
    if current is None and completed < total_steps:
        current = completed + 1 if total_steps > 0 else None
    if current is not None and current <= completed:
        current = None
    return current, completed

def build_plan_progress_snapshot(
    plan_snapshot: ResearchPlanSnapshot,
    *,
    current_step_index: int | None,
    completed_step_count: int,
    active_step_status: str = "current",
) -> dict[str, object]:
    total_steps = len(plan_snapshot.subtasks)
    bounded_completed = max(0, min(completed_step_count, total_steps))
    bounded_current = normalize_plan_progress_index(
        current_step_index, total_steps=total_steps
    )
    if bounded_current is not None and bounded_current <= bounded_completed:
        bounded_current = None

    steps: list[dict[str, object]] = []
    for index, subtask in enumerate(plan_snapshot.subtasks, start=1):
        if index <= bounded_completed:
            status = "complete"
        elif bounded_current is not None and index == bounded_current:
            status = active_step_status
        else:
            status = "pending"
        steps.append(
            {
                "index": index,
                "title": subtask.title,
                "description": subtask.description,
                "target_sources": [item.value for item in subtask.target_sources],
                "status": status,
            }
        )

    return {
        "steps": steps,
        "current_step_index": bounded_current,
        "completed_step_count": bounded_completed,
        "updated_at": plan_progress_updated_at(),
    }


def build_plan_progress_snapshot_from_runtime_todos(
    plan_snapshot: ResearchPlanSnapshot,
    *,
    todos: list[dict[str, object]],
) -> dict[str, object]:
    total_steps = len(plan_snapshot.subtasks)
    if total_steps <= 0:
        return build_plan_progress_snapshot(
            plan_snapshot,
            current_step_index=None,
            completed_step_count=0,
        )

    step_status_by_index: dict[int, str] = {}
    for item in todos:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        matched = _RUNTIME_PLAN_STEP_TODO_PATTERN.match(content)
        if matched is None:
            continue
        try:
            index = int(matched.group(1))
        except ValueError:
            continue
        normalized_index = normalize_plan_progress_index(
            index,
            total_steps=total_steps,
        )
        if normalized_index is None:
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in {"pending", "in_progress", "completed"}:
            status = "pending"
        step_status_by_index[normalized_index] = status

    completed_step_count = 0
    for index in range(1, total_steps + 1):
        if step_status_by_index.get(index) == "completed":
            completed_step_count += 1
            continue
        break

    current_step_index: int | None = next(
        (
            index
            for index in range(completed_step_count + 1, total_steps + 1)
            if step_status_by_index.get(index) == "in_progress"
        ),
        None,
    )
    if current_step_index is None and completed_step_count < total_steps:
        current_step_index = completed_step_count + 1

    return build_plan_progress_snapshot(
        plan_snapshot,
        current_step_index=current_step_index,
        completed_step_count=completed_step_count,
    )

def lc_agent_name_for_phase(phase: str) -> str:
    if phase == "planner":
        return "planner"
    if phase == "finalizer":
        return "finalizer"
    return "deep-research"

def build_plan_progress_summary(snapshot: dict[str, object]) -> str:
    steps = snapshot.get("steps")
    if not isinstance(steps, list):
        return "研究计划步骤已更新。"

    current_step = next(
        (
            item
            for item in steps
            if isinstance(item, dict)
            and item.get("status") in {"current", "failed", "canceled"}
        ),
        None,
    )
    if isinstance(current_step, dict):
        title = str(current_step.get("title") or "").strip()
        status = str(current_step.get("status") or "")
        if status == "failed":
            return f"当前计划步骤失败：{title}" if title else "当前计划步骤失败。"
        if status == "canceled":
            return f"当前计划步骤已停止：{title}" if title else "当前计划步骤已停止。"
        return f"当前计划步骤：{title}" if title else "当前计划步骤已更新。"

    completed = snapshot.get("completed_step_count")
    if isinstance(completed, int) and completed == len(steps) and len(steps) > 0:
        return "研究计划步骤已全部完成，正在生成报告。"
    return "研究计划步骤已更新。"

def normalize_plan_progress_message(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None

def plan_progress_snapshot_equals(
    left: dict[str, object] | None,
    right: dict[str, object],
) -> bool:
    if left is None:
        return False
    return (
        left.get("steps") == right.get("steps")
        and left.get("current_step_index") == right.get("current_step_index")
        and left.get("completed_step_count") == right.get("completed_step_count")
    )

def build_event_envelope(
    *,
    session: ResearchSession,
    event: ResearchEvent,
) -> ResearchEventEnvelope:
    payload = dict(event.payload or {})
    source_provider = payload.get("source_provider")
    retrieval_method = payload.get("retrieval_method")
    origin_url = payload.get("origin_url")
    lc_agent_name = payload.get("lc_agent_name")
    subagent_name = payload.get("subagent_name")
    if not isinstance(subagent_name, str) or not subagent_name.strip():
        subagent_name = subagent_name_from_namespace(
            event.namespace
        )
    return ResearchEventEnvelope(
        event_id=event.event_id,
        sequence=event.sequence,
        timestamp=event.created_at,
        event_type=event.event_type,
        session_id=session.id,
        phase=event.phase,
        namespace=event.namespace,
        payload=payload,
        trace_id=event.trace_id,
        source_provider=source_provider
        if isinstance(source_provider, str)
        else None,
        retrieval_method=retrieval_method
        if isinstance(retrieval_method, str)
        else None,
        origin_url=origin_url if isinstance(origin_url, str) else None,
        lc_agent_name=lc_agent_name if isinstance(lc_agent_name, str) else None,
        subagent_name=subagent_name if isinstance(subagent_name, str) else None,
    )

def subagent_name_from_namespace(namespace: str) -> str | None:
    normalized = str(namespace or "").strip("/")
    if not normalized or normalized == "main":
        return None
    parts = [item for item in normalized.split("/") if item]
    return parts[-1] if parts else None
