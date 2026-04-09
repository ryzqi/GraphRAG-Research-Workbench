from __future__ import annotations

from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchSourceTarget,
)
from app.services.research_workspace_files import (
    RESEARCH_BOOTSTRAP_ARTIFACT_KEYS,
    build_research_workspace_layout,
    build_workspace_bootstrap_artifacts,
)


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="验证运行时上下文工程",
        complexity=ResearchComplexity.COMPLEX,
        summary="围绕 claim map、ledger 与 rich report 搭建 runtime scaffold",
        subtasks=[],
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
    )


def test_workspace_layout_includes_runtime_context_paths() -> None:
    layout = build_research_workspace_layout("session-123")

    assert layout.claim_map_md_path.endswith("/05-claim-map.md")
    assert layout.evidence_ledger_md_path.endswith("/06-evidence-ledger.md")
    assert layout.analysis_notes_path.endswith("/07-analysis-notes.md")
    assert layout.report_outline_path.endswith("/08-report-outline.md")
    assert layout.report_context_json_path.endswith("/report/report-context.json")


def test_build_workspace_bootstrap_artifacts_seeds_runtime_context_markdown() -> None:
    artifacts = build_workspace_bootstrap_artifacts(
        session_id="session-123",
        question="当前 RAG 领域的最新进展",
        plan_snapshot=_build_plan_snapshot(),
    )

    assert {
        "claim_map_md",
        "evidence_ledger_md",
        "analysis_notes_md",
        "report_outline_md",
    }.issubset(RESEARCH_BOOTSTRAP_ARTIFACT_KEYS)
    assert "## 核心主张" in str(artifacts["claim_map_md"].content_text)
    assert "## 证据账本" in str(artifacts["evidence_ledger_md"].content_text)
    assert "## 中间分析" in str(artifacts["analysis_notes_md"].content_text)
    assert "## 报告提纲" in str(artifacts["report_outline_md"].content_text)
