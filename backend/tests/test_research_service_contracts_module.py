from __future__ import annotations

from app.schemas.research import ResearchPlanSnapshot
from app.services import research_service_contracts as contracts_module


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot.model_validate(
        {
            "research_brief": "验证 service contracts helper 模块拆分。",
            "complexity": "simple",
            "summary": "拆出 plan progress 与 artifacts response helper。",
            "subtasks": [
                {
                    "title": "整理计划步骤",
                    "description": "保持计划进度快照结构不变。",
                    "target_sources": ["web"],
                },
                {
                    "title": "收口报告",
                    "description": "保持最终 artifacts response 契约不变。",
                    "target_sources": ["web"],
                },
            ],
            "target_sources": ["web"],
        }
    )


def test_contracts_module_builds_plan_progress_snapshot() -> None:
    snapshot = contracts_module.build_plan_progress_snapshot(
        _build_plan_snapshot(),
        current_step_index=2,
        completed_step_count=1,
    )

    assert snapshot["current_step_index"] == 2
    assert snapshot["completed_step_count"] == 1
    assert snapshot["steps"][0]["status"] == "complete"
    assert snapshot["steps"][1]["status"] == "current"


def test_contracts_module_summarizes_terminal_progress() -> None:
    summary = contracts_module.build_plan_progress_summary(
        {
            "steps": [
                {"title": "整理计划步骤", "status": "complete"},
                {"title": "收口报告", "status": "failed"},
            ],
            "completed_step_count": 1,
        }
    )

    assert summary == "当前计划步骤失败：收口报告"