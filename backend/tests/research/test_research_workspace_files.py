from __future__ import annotations

import uuid

from app.schemas.research import (
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
)
from app.services.research_workspace_files import (
    RESEARCH_BOOTSTRAP_ARTIFACT_KEYS,
    build_research_workspace_layout,
    build_workspace_bootstrap_artifacts,
)


def _plan() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="比较 Deep Research OS 的 plan-first 工作流与当前卡片式工作台。",
        complexity="comparative",
        summary="先生成计划，再按 provider 覆盖执行研究。",
        target_sources=[ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER],
        subtasks=[
            ResearchPlanSubtask(
                title="规划查询网格",
                description="拆出 breadth、depth、verification 三类 query。",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
        budget_guidance="优先保证 provider 覆盖，再决定是否继续扩搜。",
    )


def test_build_research_workspace_layout_is_scoped_to_session() -> None:
    session_id = uuid.uuid4()
    layout = build_research_workspace_layout(session_id)

    assert layout.session_slug == str(session_id)
    assert layout.workspace_root == f"/workspace/research/{session_id}"
    assert layout.plan_path == f"/workspace/research/{session_id}/01-plan.md"
    assert layout.coverage_path == f"/workspace/research/{session_id}/03-coverage.md"
    assert (
        layout.source_ledger_path
        == f"/scratch/research/{session_id}/verification/source-ledger.json"
    )


def test_build_workspace_bootstrap_artifacts_contains_required_markdown_files() -> None:
    artifacts = build_workspace_bootstrap_artifacts(
        session_id=uuid.uuid4(),
        question="为什么要把 Deep Research 改成 OS？",
        plan_snapshot=_plan(),
    )

    assert tuple(artifacts) == RESEARCH_BOOTSTRAP_ARTIFACT_KEYS
    assert artifacts["mission_md"].artifact_key == "mission_md"
    assert "# Mission" in artifacts["mission_md"].content_text
    assert "为什么要把 Deep Research 改成 OS？" in artifacts["mission_md"].content_text
    assert "# Plan" in artifacts["plan_md"].content_text
    assert "规划查询网格" in artifacts["plan_md"].content_text
    assert "# Coverage" in artifacts["coverage_md"].content_text
