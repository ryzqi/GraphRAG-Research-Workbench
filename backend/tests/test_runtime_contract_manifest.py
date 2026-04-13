from __future__ import annotations

from types import SimpleNamespace

import app.services.deep_research_runtime as runtime_module
from app.config.runtime_contract import (
    DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH,
    RESEARCH_RUNTIME_BACKEND_ROOTS,
    RESEARCH_RUNTIME_LAYOUT_MANIFEST,
    RESEARCH_RUNTIME_REQUEST_CONTEXT,
    RESEARCH_RUNTIME_WORKSPACE_CONTEXT_DOCS,
)
from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
)
from app.services.research_runtime_context import build_runtime_context_guide
from app.services.research_runtime_workspace import (
    build_runtime_memory_files,
    build_runtime_prompt,
    build_runtime_request_files,
)
from app.services.research_runtime_types import DEFAULT_RESEARCH_BACKEND_POLICY
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_workspace_bootstrap_artifact_path_map,
)


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="研究 contract manifest",
        complexity=ResearchComplexity.SIMPLE,
        summary="验证 runtime contract 单一事实源。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="核对 runtime manifest",
                description="确保 layout、context、request file 统一收敛。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
    )


def _build_session() -> SimpleNamespace:
    return SimpleNamespace(
        id="session-1",
        question="runtime contract 是什么？",
        thread_id="thread-1",
        trace_id="trace-1",
    )


def test_runtime_contract_manifest_drives_layout_and_backend_policy() -> None:
    layout = build_research_workspace_layout("session-1")
    path_map = build_workspace_bootstrap_artifact_path_map(layout=layout)

    assert DEFAULT_RESEARCH_BACKEND_POLICY.workspace_root == (
        RESEARCH_RUNTIME_BACKEND_ROOTS.workspace_root
    )
    assert DEFAULT_RESEARCH_BACKEND_POLICY.scratch_root == (
        RESEARCH_RUNTIME_BACKEND_ROOTS.scratch_root
    )
    assert layout.workspace_root == "/workspace/research/session-1"
    assert layout.scratch_root == "/scratch/research/session-1"
    assert layout.report_context_json_path == (
        "/scratch/research/session-1/report/report-context.json"
    )
    assert path_map == {
        artifact_key: getattr(layout, attr_name)
        for artifact_key, attr_name in (
            RESEARCH_RUNTIME_LAYOUT_MANIFEST.bootstrap_artifact_key_to_attr
        )
    }


def test_runtime_contract_manifest_drives_context_guide_request_files_and_prompt() -> None:
    session = _build_session()
    plan_snapshot = _build_plan_snapshot()
    layout = build_research_workspace_layout(session.id)
    workspace_files = {
        layout.mission_path: "# mission\n",
        layout.plan_path: "# plan\n",
        layout.query_map_path: "# query-map\n",
        layout.coverage_path: "# coverage\n",
        layout.task_graph_path: "{}",
        layout.claim_bundles_path: "[]",
        layout.section_briefs_path: "[]",
        layout.report_context_json_path: "{}",
        layout.claim_map_md_path: "# claim-map\n",
        layout.evidence_ledger_md_path: "# evidence-ledger\n",
        layout.analysis_notes_path: "# analysis\n",
        layout.report_outline_path: "# outline\n",
        layout.report_draft_path: "# draft\n",
        layout.live_board_path: "{}",
        DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH: "# runtime-memory\n",
    }

    guide = build_runtime_context_guide(workspace_files=workspace_files, layout=layout)
    request_files = build_runtime_request_files(
        workspace_files=workspace_files,
        session=session,
        plan_snapshot=plan_snapshot,
    )
    prompt = build_runtime_prompt(
        session=session,
        plan_snapshot=plan_snapshot,
        workspace_paths=guide.priority_paths,
    )

    assert guide.path == RESEARCH_RUNTIME_REQUEST_CONTEXT.guide_path
    assert guide.priority_paths[0] == RESEARCH_RUNTIME_REQUEST_CONTEXT.guide_path
    assert request_files.keys() >= {
        RESEARCH_RUNTIME_REQUEST_CONTEXT.session_question_path,
        RESEARCH_RUNTIME_REQUEST_CONTEXT.plan_snapshot_path,
        RESEARCH_RUNTIME_REQUEST_CONTEXT.query_mesh_path,
    }
    assert RESEARCH_RUNTIME_REQUEST_CONTEXT.query_mesh_path in prompt


def test_runtime_contract_manifest_drives_memory_and_workspace_docs() -> None:
    session = _build_session()
    plan_snapshot = _build_plan_snapshot()

    memory_files = build_runtime_memory_files(
        session=session,
        plan_snapshot=plan_snapshot,
    )
    workspace_context_files = runtime_module._build_workspace_context_files()
    expected_workspace_doc_paths = {
        doc.virtual_path
        for doc in RESEARCH_RUNTIME_WORKSPACE_CONTEXT_DOCS
        if doc.disk_path.exists()
    }

    assert set(memory_files) == {DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH}
    assert set(workspace_context_files) == expected_workspace_doc_paths
