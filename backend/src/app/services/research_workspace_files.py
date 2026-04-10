"""研究会话 workspace bootstrap 工件。"""

from __future__ import annotations

import json
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
    "claim_map_md",
    "evidence_ledger_md",
    "analysis_notes_md",
    "report_outline_md",
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
    claim_map_md_path: str
    evidence_ledger_md_path: str
    analysis_notes_path: str
    report_outline_path: str
    task_graph_path: str
    claim_bundles_path: str
    section_briefs_path: str
    live_board_path: str
    source_ledger_path: str
    claim_map_path: str
    conflicts_path: str
    report_context_json_path: str


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
        claim_map_md_path=f"{workspace_root}/05-claim-map.md",
        evidence_ledger_md_path=f"{workspace_root}/06-evidence-ledger.md",
        analysis_notes_path=f"{workspace_root}/07-analysis-notes.md",
        report_outline_path=f"{workspace_root}/08-report-outline.md",
        task_graph_path=f"{workspace_root}/09-task-graph.json",
        claim_bundles_path=f"{workspace_root}/10-claim-bundles.json",
        section_briefs_path=f"{workspace_root}/11-section-briefs.json",
        live_board_path=f"{workspace_root}/12-live-board.json",
        source_ledger_path=f"{scratch_root}/verification/source-ledger.json",
        claim_map_path=f"{scratch_root}/verification/claim-map.json",
        conflicts_path=f"{scratch_root}/verification/conflicts.json",
        report_context_json_path=f"{scratch_root}/report/report-context.json",
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
        "claim_map_md": layout.claim_map_md_path,
        "evidence_ledger_md": layout.evidence_ledger_md_path,
        "analysis_notes_md": layout.analysis_notes_path,
        "report_outline_md": layout.report_outline_path,
        "task_graph_json": layout.task_graph_path,
        "claim_bundles_json": layout.claim_bundles_path,
        "section_briefs_json": layout.section_briefs_path,
        "live_board_json": layout.live_board_path,
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
        "claim_map_md": ResearchArtifactSeed(
            artifact_key="claim_map_md",
            content_text=prompts.render("research/claim_map_md"),
        ),
        "evidence_ledger_md": ResearchArtifactSeed(
            artifact_key="evidence_ledger_md",
            content_text=prompts.render("research/evidence_ledger_md"),
        ),
        "analysis_notes_md": ResearchArtifactSeed(
            artifact_key="analysis_notes_md",
            content_text=prompts.render("research/analysis_notes_md"),
        ),
        "report_outline_md": ResearchArtifactSeed(
            artifact_key="report_outline_md",
            content_text=prompts.render("research/report_outline_md"),
        ),
    }


def build_runtime_task_graph_payload(
    *,
    question: str,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    subtasks = list(plan_snapshot.subtasks)
    if not subtasks:
        subtasks = [
            ResearchPlanSubtask(
                title="初始化研究任务图",
                description="主代理先拆解 claim、来源和章节任务，再决定并行分发。",
                target_sources=plan_snapshot.target_sources,
            )
        ]
    for index, subtask in enumerate(subtasks, start=1):
        task_id = f"subtask-{index}"
        tasks.append(
            {
                "task_id": task_id,
                "title": subtask.title,
                "description": subtask.description,
                "task_kind": "subtask",
                "status": "pending",
                "owner": "supervisor",
                "parallel_group": task_id,
                "target_sources": [item.value for item in subtask.target_sources],
                "depends_on": [f"subtask-{index - 1}"] if index > 1 else [],
                "can_parallelize": len(subtask.target_sources) > 1,
            }
        )
    return {
        "question": question,
        "execution_mode": "quality_first",
        "tasks": tasks,
    }


def build_runtime_section_briefs_payload(
    *,
    plan_snapshot: ResearchPlanSnapshot,
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    for index, subtask in enumerate(plan_snapshot.subtasks, start=1):
        briefs.append(
            {
                "section_id": f"section-{index}",
                "task_id": f"subtask-{index}",
                "title": subtask.title,
                "status": "pending",
                "target_sources": [item.value for item in subtask.target_sources],
                "summary": "",
                "brief_markdown": "",
                "open_questions": [],
                "citation_indices": [],
            }
        )
    return briefs


def build_runtime_claim_bundles_payload() -> list[dict[str, Any]]:
    return []


def build_runtime_live_board_payload(
    *,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, Any]:
    task_graph = build_runtime_task_graph_payload(
        question="",
        plan_snapshot=plan_snapshot,
    )
    tasks = task_graph.get("tasks")
    first_task = tasks[0] if isinstance(tasks, list) and tasks else None
    return {
        "current_agent_label": "deep-research",
        "current_task_id": (
            str(first_task.get("task_id") or "").strip()
            if isinstance(first_task, dict)
            else None
        ),
        "current_task_label": (
            str(first_task.get("title") or "").strip()
            if isinstance(first_task, dict)
            else None
        ),
        "current_task_kind": (
            str(first_task.get("task_kind") or "").strip()
            if isinstance(first_task, dict)
            else None
        ),
        "status_message": "主代理正在初始化研究任务图。",
        "parallel_tasks": [],
        "recent_activity": [],
    }


def build_runtime_orchestration_scaffold_files(
    *,
    question: str,
    plan_snapshot: ResearchPlanSnapshot,
    layout: ResearchWorkspaceLayout,
) -> dict[str, str]:
    return {
        layout.task_graph_path: json.dumps(
            build_runtime_task_graph_payload(
                question=question,
                plan_snapshot=plan_snapshot,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        layout.claim_bundles_path: json.dumps(
            build_runtime_claim_bundles_payload(),
            ensure_ascii=False,
            indent=2,
        ),
        layout.section_briefs_path: json.dumps(
            build_runtime_section_briefs_payload(plan_snapshot=plan_snapshot),
            ensure_ascii=False,
            indent=2,
        ),
        layout.live_board_path: json.dumps(
            build_runtime_live_board_payload(plan_snapshot=plan_snapshot),
            ensure_ascii=False,
            indent=2,
        ),
    }
