from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_runtime_types import ResearchRuntimeActivityUpdate
from app.services.research_workspace_files import (
    build_runtime_live_board_payload,
    build_runtime_task_graph_payload,
)
from app.services.research_finalizer import ResearchFinalizerResult


def _json_mapping_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


async def persist_runtime_context_artifacts(
    *,
    artifact_store: Any,
    session: ResearchSession,
    runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
    task_graph_artifact_key: str,
    live_board_artifact_key: str,
) -> None:
    if runtime_context_snapshot is None:
        return

    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_claim_map_json',
        content_json=runtime_context_snapshot.claim_map_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_evidence_ledger_json',
        content_json=runtime_context_snapshot.evidence_ledger_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_claim_map_md',
        content_text=runtime_context_snapshot.claim_map_md,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_evidence_ledger_md',
        content_text=runtime_context_snapshot.evidence_ledger_md,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_analysis_notes_md',
        content_text=runtime_context_snapshot.analysis_notes_md,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_report_outline_md',
        content_text=runtime_context_snapshot.report_outline_md,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_report_draft_md',
        content_text=runtime_context_snapshot.report_draft_md,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_report_context_json',
        content_json=runtime_context_snapshot.report_context_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key=task_graph_artifact_key,
        content_json=runtime_context_snapshot.task_graph_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_claim_bundles_json',
        content_json=runtime_context_snapshot.claim_bundles_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_section_briefs_json',
        content_json=runtime_context_snapshot.section_briefs_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key=live_board_artifact_key,
        content_json=runtime_context_snapshot.live_board_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='runtime_files_snapshot_json',
        content_json=runtime_context_snapshot.files_snapshot,
    )


def merge_runtime_projection_snapshot(
    *,
    live_board_projection: dict[str, object] | None,
    runtime_context_snapshot: ResearchRuntimeContextSnapshot | None,
) -> ResearchRuntimeContextSnapshot | None:
    if runtime_context_snapshot is None:
        return None
    if not isinstance(live_board_projection, dict):
        return runtime_context_snapshot
    return replace(
        runtime_context_snapshot,
        live_board_json=dict(live_board_projection),
    )


async def persist_final_report_artifacts(
    *,
    artifact_store: Any,
    session: ResearchSession,
    final_result: ResearchFinalizerResult,
) -> None:
    await artifact_store.upsert(
        session=session,
        artifact_key='report_json',
        content_json=final_result.report_json,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='report_md',
        content_text=final_result.report_md,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='claim_map_json',
        content_json=final_result.report_json['claim_map'],
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='coverage_matrix_json',
        content_json=final_result.report_json['coverage_matrix'],
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='conflicts_json',
        content_json=final_result.report_json['conflicts'],
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='source_ledger_json',
        content_json=final_result.report_json['source_ledger'],
    )


async def persist_metrics_artifacts(
    *,
    artifact_store: Any,
    session: ResearchSession,
    metrics: dict[str, object],
) -> None:
    session.metrics = dict(metrics)
    await artifact_store.upsert(
        session=session,
        artifact_key='metrics_snapshot',
        content_json=dict(metrics),
    )
    await artifact_store.upsert(
        session=session,
        artifact_key='gate_snapshot',
        content_json=_json_mapping_payload(metrics.get('gate')),
    )
    quality_payload = metrics.get('quality_snapshot')
    if isinstance(quality_payload, dict):
        await artifact_store.upsert(
            session=session,
            artifact_key='quality_snapshot',
            content_json=_json_mapping_payload(quality_payload),
        )


def runtime_live_board_updated_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json_artifact(
    session: ResearchSession,
    artifact_key: str,
) -> dict[str, object] | list[object] | None:
    artifact = next(
        (item for item in session.artifacts if item.artifact_key == artifact_key),
        None,
    )
    payload = artifact.content_json if artifact is not None else None
    if isinstance(payload, (dict, list)):
        return payload
    return None


async def persist_runtime_execution_artifacts(
    *,
    artifact_store: Any,
    session: ResearchSession,
    plan_snapshot: Any,
    task_graph_artifact_key: str,
    live_board_artifact_key: str,
) -> None:
    task_graph = build_runtime_task_graph_payload(
        question=session.question,
        plan_snapshot=plan_snapshot,
    )
    live_board = build_runtime_live_board_payload(plan_snapshot=plan_snapshot)
    live_board['updated_at'] = runtime_live_board_updated_at()
    await artifact_store.upsert(
        session=session,
        artifact_key=task_graph_artifact_key,
        content_json=task_graph,
    )
    await artifact_store.upsert(
        session=session,
        artifact_key=live_board_artifact_key,
        content_json=live_board,
    )


async def persist_runtime_activity_update(
    *,
    artifact_store: Any,
    session: ResearchSession,
    update: ResearchRuntimeActivityUpdate,
    live_board_artifact_key: str,
) -> dict[str, object]:
    existing_payload = read_json_artifact(session, live_board_artifact_key)
    live_board = dict(existing_payload) if isinstance(existing_payload, dict) else {}
    existing_parallel_tasks = live_board.get('parallel_tasks')
    active_tasks: dict[str, dict[str, object]] = {}
    if isinstance(existing_parallel_tasks, list):
        for item in existing_parallel_tasks:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get('task_id') or '').strip()
            if task_id:
                active_tasks[task_id] = dict(item)

    task_entry = {
        'task_id': update.task_id,
        'title': update.title,
        'task_kind': update.task_kind,
        'status': update.status,
        'agent_label': update.subagent_name or update.agent_name,
        'parallel_group': update.parallel_group,
    }
    if update.status in {'started', 'in_progress'}:
        active_tasks[update.task_id] = task_entry
    else:
        active_tasks.pop(update.task_id, None)

    current_task = (
        task_entry
        if update.status in {'started', 'in_progress'}
        else next(iter(active_tasks.values()), None)
    )

    existing_activity = live_board.get('recent_activity')
    recent_activity = (
        [item for item in existing_activity if isinstance(item, dict)]
        if isinstance(existing_activity, list)
        else []
    )
    recent_activity = [
        {
            'task_id': update.task_id,
            'title': update.title,
            'task_kind': update.task_kind,
            'status': update.status,
            'agent_label': update.subagent_name or update.agent_name,
            'parallel_group': update.parallel_group,
            'message': update.message,
            'timestamp': runtime_live_board_updated_at(),
        },
        *recent_activity,
    ][:8]

    next_live_board: dict[str, object] = {
        **live_board,
        'current_agent_label': (
            str(current_task.get('agent_label') or '').strip()
            if isinstance(current_task, dict)
            else None
        ),
        'current_task_id': (
            str(current_task.get('task_id') or '').strip()
            if isinstance(current_task, dict)
            else None
        ),
        'current_task_label': (
            str(current_task.get('title') or '').strip()
            if isinstance(current_task, dict)
            else None
        ),
        'current_task_kind': (
            str(current_task.get('task_kind') or '').strip()
            if isinstance(current_task, dict)
            else None
        ),
        'status_message': update.message or update.title,
        'parallel_tasks': list(active_tasks.values()),
        'recent_activity': recent_activity,
        'updated_at': runtime_live_board_updated_at(),
    }
    await artifact_store.upsert(
        session=session,
        artifact_key=live_board_artifact_key,
        content_json=next_live_board,
    )
    return next_live_board


async def append_trace_events(
    *,
    event_store: Any,
    session: ResearchSession,
    trace_links: list[dict[str, object]],
) -> None:
    for item in trace_links:
        namespace = str(item.get('namespace') or 'main')
        lc_agent_name = str(item.get('lc_agent_name') or '').strip()
        source_provider = item.get('source_provider')
        if namespace == 'main' and lc_agent_name == 'deep-research':
            continue
        await event_store.append(
            session=session,
            event_type='research.trace.recorded',
            phase='runtime',
            namespace=namespace,
            payload={
                'lc_agent_name': lc_agent_name,
                'source_provider': source_provider,
            },
            trace_id=str(item.get('trace_id') or session.trace_id or ''),
        )


async def read_committed_session_status(
    *,
    db: Any,
    session: ResearchSession,
) -> ResearchSessionStatus | None:
    if session.id is None or not callable(getattr(db, 'scalar', None)):
        return None

    stmt = select(ResearchSession.status).where(ResearchSession.id == session.id)
    no_autoflush = getattr(db, 'no_autoflush', None)
    if no_autoflush is None:
        resolved_status = await db.scalar(stmt)
    else:
        with no_autoflush:
            resolved_status = await db.scalar(stmt)

    if isinstance(resolved_status, ResearchSessionStatus):
        return resolved_status
    if isinstance(resolved_status, str):
        try:
            return ResearchSessionStatus(resolved_status)
        except ValueError:
            return None
    return None
