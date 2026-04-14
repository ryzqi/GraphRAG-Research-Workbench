from __future__ import annotations

from pathlib import Path

from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
)
from app.services.research_runtime_skills import build_research_runtime_skill_files
from app.services.research_service_contracts import (
    build_plan_progress_snapshot_from_runtime_todos,
)


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="验证 Deep Agents todo 作为计划事实源",
        complexity=ResearchComplexity.SIMPLE,
        summary="确保 runtime plan progress 从 todos 收敛。",
        target_sources=[ResearchSourceTarget.WEB],
        subtasks=[
            ResearchPlanSubtask(
                title="梳理问题与范围",
                description="补齐问题背景与边界。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
            ResearchPlanSubtask(
                title="验证关键主张",
                description="为核心主张补齐证据。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
            ResearchPlanSubtask(
                title="输出研究结论",
                description="形成最终 findings 与 citations。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
        ],
    )


def test_build_plan_progress_snapshot_from_runtime_todos_maps_plan_step_markers() -> None:
    snapshot = build_plan_progress_snapshot_from_runtime_todos(
        _build_plan_snapshot(),
        todos=[
            {"content": "[plan-step-1] 梳理问题与范围", "status": "completed"},
            {"content": "[plan-step-2] 验证关键主张", "status": "in_progress"},
            {"content": "[plan-step-3] 输出研究结论", "status": "pending"},
            {"content": "补齐 claim-1 网页证据", "status": "pending"},
        ],
    )

    assert snapshot["current_step_index"] == 2
    assert snapshot["completed_step_count"] == 1
    assert [item["status"] for item in snapshot["steps"]] == [
        "complete",
        "current",
        "pending",
    ]


def test_build_plan_progress_snapshot_from_runtime_todos_promotes_next_pending_step() -> None:
    snapshot = build_plan_progress_snapshot_from_runtime_todos(
        _build_plan_snapshot(),
        todos=[
            {"content": "[plan-step-1] 梳理问题与范围", "status": "completed"},
            {"content": "[plan-step-2] 验证关键主张", "status": "pending"},
            {"content": "[plan-step-3] 输出研究结论", "status": "pending"},
        ],
    )

    assert snapshot["current_step_index"] == 2
    assert snapshot["completed_step_count"] == 1
    assert [item["status"] for item in snapshot["steps"]] == [
        "complete",
        "current",
        "pending",
    ]


def test_research_runtime_guidance_uses_write_todos_as_single_plan_progress_source() -> None:
    skill_text = build_research_runtime_skill_files()[
        "/skills/research-runtime/SKILL.md"
    ]

    assert "update_plan_progress" not in skill_text
    assert "[plan-step-" in skill_text

    backend_root = Path(__file__).resolve().parents[1]
    prompt_paths = [
        backend_root / "src" / "app" / "prompts" / "templates" / "research" / "runtime_system.yaml",
        backend_root / "src" / "app" / "prompts" / "templates" / "research" / "runtime_user.yaml",
    ]
    for path in prompt_paths:
        content = path.read_text(encoding="utf-8")
        assert "update_plan_progress" not in content
        assert "[plan-step-" in content
