from __future__ import annotations

import asyncio
import uuid

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_service_execution import (
    merge_runtime_projection_snapshot,
    persist_metrics_artifacts,
)


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None]] = []

    async def upsert(
        self,
        *,
        session: ResearchSession,
        artifact_key: str,
        content_text: str | None = None,
        content_json: object | None = None,
        **_: object,
    ) -> None:
        del session, content_text
        self.calls.append((artifact_key, content_json))


def test_merge_runtime_projection_snapshot_prefers_service_live_board() -> None:
    snapshot = merge_runtime_projection_snapshot(
        live_board_projection={
            'current_task_label': 'service-owned',
            'recent_activity': [{'task_id': 'claim-1', 'status': 'completed'}],
        },
        runtime_context_snapshot=ResearchRuntimeContextSnapshot(
            task_graph_json={'tasks': [{'task_id': 'claim-1'}]},
            live_board_json={
                'current_task_label': 'agent-authored',
                'recent_activity': [{'task_id': 'claim-1', 'status': 'running'}],
            },
        ),
    )

    assert snapshot is not None
    assert snapshot.live_board_json['current_task_label'] == 'service-owned'
    assert snapshot.live_board_json['recent_activity'][0]['status'] == 'completed'


def test_persist_metrics_artifacts_updates_session_and_gate_snapshot() -> None:
    store = _FakeArtifactStore()
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id='thread-1',
        question='如何验证 metrics 持久化？',
        status=ResearchSessionStatus.RUNNING,
    )
    metrics = {
        'quality': {'citation_count': 1, 'finding_count': 2},
        'gate': {'pass': True},
    }

    asyncio.run(
        persist_metrics_artifacts(
            artifact_store=store,
            session=session,
            metrics=metrics,
        )
    )

    assert session.metrics == metrics
    assert ('metrics_snapshot', metrics) in store.calls
    assert ('gate_snapshot', {'pass': True}) in store.calls
