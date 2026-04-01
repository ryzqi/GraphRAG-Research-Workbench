"""研究会话 workspace bootstrap 工件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchPlanSnapshot, ResearchPlanSubtask

RESEARCH_BOOTSTRAP_ARTIFACT_KEYS = (
    "mission_md",
    "plan_md",
    "query_map_md",
    "coverage_md",
    "report_draft_md",
)


@dataclass(slots=True, frozen=True)
class ResearchWorkspaceLayout:
    session_slug: str
    workspace_root: str
    scratch_root: str
    mission_path: str
    plan_path: str
    query_map_path: str
    coverage_path: str
    report_draft_path: str
    source_ledger_path: str
    claim_map_path: str
    conflicts_path: str


@dataclass(slots=True, frozen=True)
class ResearchArtifactSeed:
    artifact_key: str
    content_text: str | None = None
    content_json: dict[str, Any] | list[Any] | None = None


def _format_target_sources(plan_snapshot: ResearchPlanSnapshot) -> str:
    return ", ".join(item.value for item in plan_snapshot.target_sources) or "web"


def _describe_expected_evidence(subtask: ResearchPlanSubtask) -> str:
    source_labels = ", ".join(item.value for item in subtask.target_sources) or "web"
    return f"优先收集 {source_labels} 的官方资料、原始材料与可核查引用。"


def _describe_verification_action(subtask: ResearchPlanSubtask) -> str:
    if any(item.value == "paper" for item in subtask.target_sources):
        return "至少进行一次官方资料交叉验证，并补搜论文、限制、争议与反例。"
    return "至少进行一次官方资料交叉验证，并补搜限制、争议与反例。"


def _build_subtasks_block(plan_snapshot: ResearchPlanSnapshot) -> str:
    if not plan_snapshot.subtasks:
        return (
            "### 1. 等待 planner 生成子任务\n"
            "- 任务目的：等待研究规划产出可执行子任务。\n"
            "- 预期证据：至少一类高可信来源。\n"
            "- 验证动作：完成后补做交叉验证与风险梳理。"
        )

    parts: list[str] = []
    for index, item in enumerate(plan_snapshot.subtasks, start=1):
        parts.append(
            "\n".join(
                [
                    f"### {index}. {item.title}",
                    f"- 任务目的：{item.description}",
                    f"- 预期证据：{_describe_expected_evidence(item)}",
                    f"- 验证动作：{_describe_verification_action(item)}",
                ]
            )
        )
    return "\n\n".join(parts)


def build_research_workspace_layout(session_id: UUID | str) -> ResearchWorkspaceLayout:
    slug = str(session_id)
    workspace_root = f"/workspace/research/{slug}"
    scratch_root = f"/scratch/research/{slug}"
    return ResearchWorkspaceLayout(
        session_slug=slug,
        workspace_root=workspace_root,
        scratch_root=scratch_root,
        mission_path=f"{workspace_root}/00-mission.md",
        plan_path=f"{workspace_root}/01-plan.md",
        query_map_path=f"{workspace_root}/02-query-map.md",
        coverage_path=f"{workspace_root}/03-coverage.md",
        report_draft_path=f"{workspace_root}/04-report-draft.md",
        source_ledger_path=f"{scratch_root}/verification/source-ledger.json",
        claim_map_path=f"{scratch_root}/verification/claim-map.json",
        conflicts_path=f"{scratch_root}/verification/conflicts.json",
    )


def build_workspace_bootstrap_artifact_path_map(
    *,
    session_id: UUID | str | None = None,
    layout: ResearchWorkspaceLayout | None = None,
) -> dict[str, str]:
    if layout is None:
        if session_id is None:
            raise ValueError("session_id 或 layout 至少提供一个。")
        layout = build_research_workspace_layout(session_id)
    return {
        "mission_md": layout.mission_path,
        "plan_md": layout.plan_path,
        "query_map_md": layout.query_map_path,
        "coverage_md": layout.coverage_path,
        "report_draft_md": layout.report_draft_path,
    }


def build_workspace_bootstrap_artifacts(
    *,
    session_id: UUID | str,
    question: str,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, ResearchArtifactSeed]:
    layout = build_research_workspace_layout(session_id)
    prompts = get_prompt_loader()
    subtasks_block = _build_subtasks_block(plan_snapshot)
    return {
        "mission_md": ResearchArtifactSeed(
            artifact_key="mission_md",
            content_text=prompts.render(
                "research/mission_md",
                session_slug=layout.session_slug,
                question=question,
                research_brief=plan_snapshot.research_brief,
                target_sources_line=_format_target_sources(plan_snapshot),
                budget_guidance=plan_snapshot.budget_guidance
                or "未显式提供，按最小必要补证执行。",
            ),
        ),
        "plan_md": ResearchArtifactSeed(
            artifact_key="plan_md",
            content_text=prompts.render(
                "research/plan_md",
                summary=plan_snapshot.summary,
                subtasks_block=subtasks_block,
            ),
        ),
        "query_map_md": ResearchArtifactSeed(
            artifact_key="query_map_md",
            content_text=prompts.render("research/query_map_md"),
        ),
        "coverage_md": ResearchArtifactSeed(
            artifact_key="coverage_md",
            content_text=prompts.render("research/coverage_md"),
        ),
        "report_draft_md": ResearchArtifactSeed(
            artifact_key="report_draft_md",
            content_text=prompts.render("research/report_draft_md"),
        ),
    }
