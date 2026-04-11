from __future__ import annotations

import uuid

from app.models.research_session import ResearchSession, ResearchSessionStatus
from app.schemas.research import (
    ResearchArtifactRead,
    ResearchCanonicalCitation,
    ResearchPlanSnapshot,
)
from app.services.research_presentation_snapshot import (
    build_research_presentation_snapshot,
)
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import build_runtime_context_snapshot
from app.services.research_source_bundle import ResearchSourceBundle
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_runtime_live_board_payload,
    build_workspace_bootstrap_artifact_path_map,
)
from app.schemas.research import ResearchSourceTarget, ResearchSourceType


def _build_web_citation() -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation(
        source_type=ResearchSourceType.WEB,
        source_provider="tavily",
        retrieval_method="web_search",
        source_id="https://example.com/rag",
        title="RAG latest",
        url="https://example.com/rag",
        origin_url="https://example.com/rag",
    )


def test_runtime_workspace_bootstrap_omits_agent_runs_artifact_and_live_board_field() -> None:
    layout = build_research_workspace_layout("session-1")
    artifact_path_map = build_workspace_bootstrap_artifact_path_map(layout=layout)
    live_board = build_runtime_live_board_payload(
        plan_snapshot=ResearchPlanSnapshot.model_validate(
            {
                "research_brief": "brief",
                "complexity": "simple",
                "summary": "summary",
                "subtasks": [
                    {
                        "title": "收集资料",
                        "description": "desc",
                        "target_sources": ["web"],
                    }
                ],
                "target_sources": ["web"],
            }
        )
    )

    assert not hasattr(layout, "agent_runs_path")
    assert "agent_runs_json" not in artifact_path_map
    assert "agent_runs" not in live_board


def test_runtime_context_snapshot_ignores_agent_runs_file() -> None:
    layout = build_research_workspace_layout("session-1")
    legacy_agent_runs_path = "/workspace/research/session-1/12-agent-runs.json"
    snapshot = build_runtime_context_snapshot(
        result={
            "files": {
                layout.task_graph_path: {
                    "content": '{"tasks":[{"task_id":"claim-1","title":"验证 claim","task_kind":"claim","status":"pending"}]}'
                },
                legacy_agent_runs_path: {
                    "content": '[{"agent_label":"deep-research","status":"ready"}]'
                },
                layout.live_board_path: {
                    "content": '{"current_agent_label":"web","current_task_label":"验证 claim"}'
                },
            }
        },
        layout=layout,
    )

    assert snapshot is not None
    assert not hasattr(layout, "agent_runs_path")
    assert not hasattr(snapshot, "agent_runs_json")
    assert snapshot.task_graph_json["tasks"][0]["task_id"] == "claim-1"
    assert legacy_agent_runs_path not in snapshot.files_snapshot
    assert layout.live_board_path not in snapshot.files_snapshot
    assert snapshot.live_board_json == {}


def test_presentation_snapshot_live_section_omits_agent_runs() -> None:
    session = ResearchSession(
        id=uuid.uuid4(),
        thread_id="thread-1",
        question="当前 RAG 领域的最新进展",
        status=ResearchSessionStatus.RUNNING,
    )
    artifacts = [
        ResearchArtifactRead(
            artifact_key="plan_snapshot",
            content_json={
                "research_brief": "brief",
                "complexity": "simple",
                "summary": "summary",
                "subtasks": [
                    {
                        "title": "验证 claim",
                        "description": "desc",
                        "target_sources": ["web"],
                    }
                ],
                "target_sources": ["web"],
            },
            citations=[],
        ),
        ResearchArtifactRead(
            artifact_key="runtime_live_board_json",
            content_json={
                "current_agent_label": "web",
                "current_task_label": "验证 claim",
                "current_task_kind": "claim",
                "parallel_tasks": [],
                "agent_runs": [
                    {
                        "agent_label": "web",
                        "status": "running",
                        "completed_task_count": 0,
                        "active_task_count": 1,
                    }
                ],
            },
            citations=[],
        ),
    ]

    snapshot = build_research_presentation_snapshot(
        session=session,
        events=[],
        artifacts=artifacts,
    )

    assert snapshot["live"] is not None
    assert "agent_runs" not in snapshot["live"]


def test_compiled_runtime_report_does_not_render_agent_run_summary() -> None:
    source_bundle = ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[_build_web_citation()],
        findings=["结论 A"],
        interim_summary="已得到结论 A",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )
    runtime_context_snapshot = build_runtime_context_snapshot(
        result={
            "files": {
                "/workspace/research/session-1/09-task-graph.json": {
                    "content": '{"tasks":[{"title":"验证 claim","task_kind":"claim","status":"pending"}]}'
                },
                "/workspace/research/session-1/12-agent-runs.json": {
                    "content": '[{"agent_label":"web","status":"running","completed_task_count":0,"active_task_count":1}]'
                },
            }
        },
        layout=build_research_workspace_layout("session-1"),
    )

    compiled = compile_report_from_runtime_context(
        question="当前 RAG 领域的最新进展",
        source_bundle=source_bundle,
        runtime_context_snapshot=runtime_context_snapshot,
    )

    assert compiled is not None
    assert "代理执行分工" not in compiled.report_md
