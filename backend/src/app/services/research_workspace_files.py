"""研究会话 workspace bootstrap 工件。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.prompts import get_prompt_loader
from app.schemas.research import ResearchPlanSnapshot, ResearchPlanSubtask

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


def _target_source_values(subtask: ResearchPlanSubtask) -> list[str]:
    return [item.value for item in subtask.target_sources]


def _source_owner(source: str) -> str:
    if source == "paper":
        return "paper"
    if source == "web":
        return "web"
    return "claim-verifier"


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
    section_task_ids: list[str] = []
    for index, subtask in enumerate(subtasks, start=1):
        section_id = f"section-{index}"
        claim_id = f"claim-{index}"
        claim_task_id = f"claim-{index}"
        source_parallel_group = f"evidence-{index}"
        subtask_sources = _target_source_values(subtask)
        previous_section_task_id = section_task_ids[-1] if section_task_ids else None
        tasks.append(
            {
                "task_id": claim_task_id,
                "title": f"收口主张：{subtask.title}",
                "description": subtask.description,
                "task_kind": "claim",
                "status": "pending",
                "owner": "claim-verifier",
                "parallel_group": claim_task_id,
                "target_sources": list(subtask_sources),
                "depends_on": [previous_section_task_id] if previous_section_task_id else [],
                "can_parallelize": False,
                "subtask_index": index,
                "section_id": section_id,
                "claim_id": claim_id,
                "deliverables": [
                    "claim_map_md",
                    "claim_bundles_json",
                ],
                "acceptance_criteria": [
                    "明确当前子任务要验证的核心 claim、反例与开放问题。",
                    "把 claim 与 section 关系写入 claim-bundles.json。",
                ],
            }
        )
        source_task_ids: list[str] = []
        for source in subtask_sources:
            source_task_id = f"source-{index}-{source}"
            source_task_ids.append(source_task_id)
            tasks.append(
                {
                    "task_id": source_task_id,
                    "title": f"{subtask.title} · {source} 证据补强",
                    "description": _describe_expected_evidence(subtask),
                    "task_kind": "source",
                    "status": "pending",
                    "owner": _source_owner(source),
                    "parallel_group": source_parallel_group,
                    "target_sources": [source],
                    "depends_on": [claim_task_id],
                    "can_parallelize": len(subtask_sources) > 1,
                    "subtask_index": index,
                    "section_id": section_id,
                    "claim_id": claim_id,
                    "deliverables": [
                        "evidence_ledger_md",
                        "claim_bundles_json",
                        "analysis_notes_md",
                    ],
                    "acceptance_criteria": [
                        _describe_expected_evidence(subtask),
                        _describe_verification_action(subtask),
                    ],
                }
            )
        section_task_id = f"section-{index}"
        tasks.append(
            {
                "task_id": section_task_id,
                "title": f"扩写章节：{subtask.title}",
                "description": "只消费已验证工件，产出章节简报、提纲更新与草稿扩写。",
                "task_kind": "section",
                "status": "pending",
                "owner": "section-writer",
                "parallel_group": section_task_id,
                "target_sources": list(subtask_sources),
                "depends_on": source_task_ids or [claim_task_id],
                "can_parallelize": False,
                "subtask_index": index,
                "section_id": section_id,
                "claim_id": claim_id,
                "deliverables": [
                    "section_briefs_json",
                    "report_outline_md",
                    "report_draft_md",
                ],
                "acceptance_criteria": [
                    "章节简报必须包含结论、证据、限制、开放问题与 citation indices。",
                    "报告草稿不得越过未闭合的 claim 直接下确定性结论。",
                ],
            }
        )
        section_task_ids.append(section_task_id)
    tasks.append(
        {
            "task_id": "report-synthesis",
            "title": "统一收口执行摘要、建议与引用审计",
            "description": "汇总章节、校对 citation 覆盖，并更新 report-context.json。",
            "task_kind": "report",
            "status": "pending",
            "owner": "citation",
            "parallel_group": "report-synthesis",
            "target_sources": [item.value for item in plan_snapshot.target_sources],
            "depends_on": list(section_task_ids),
            "can_parallelize": False,
            "deliverables": [
                "report_draft_md",
                "report_context_json",
                "evidence_ledger_md",
            ],
            "acceptance_criteria": [
                "执行摘要、关键要点、建议、开放问题与置信度全部写入 report-context.json。",
                "最终报告正文与 citation 索引保持一致。",
            ],
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
    subtasks = list(plan_snapshot.subtasks)
    if not subtasks:
        subtasks = [
            ResearchPlanSubtask(
                title="初始化章节结构",
                description="先把研究问题拆成可写作章节，再开始补证。",
                target_sources=plan_snapshot.target_sources,
            )
        ]
    for index, subtask in enumerate(subtasks, start=1):
        briefs.append(
            {
                "section_id": f"section-{index}",
                "task_id": f"section-{index}",
                "title": subtask.title,
                "status": "pending",
                "target_sources": _target_source_values(subtask),
                "angle": subtask.description,
                "summary": "",
                "brief_markdown": "",
                "must_cover": [
                    "章节主结论",
                    "直接证据与 citation 索引",
                    "限制、反例与不确定性",
                ],
                "evidence_targets": [
                    _describe_expected_evidence(subtask),
                    _describe_verification_action(subtask),
                ],
                "counterpoints": [],
                "open_questions": [],
                "citation_indices": [],
            }
        )
    return briefs


def build_runtime_claim_bundles_payload(
    *,
    plan_snapshot: ResearchPlanSnapshot,
) -> list[dict[str, Any]]:
    subtasks = list(plan_snapshot.subtasks)
    if not subtasks:
        subtasks = [
            ResearchPlanSubtask(
                title="初始化 claim",
                description="从研究问题中提炼首轮 claim 和待证伪问题。",
                target_sources=plan_snapshot.target_sources,
            )
        ]
    bundles: list[dict[str, Any]] = []
    for index, subtask in enumerate(subtasks, start=1):
        bundles.append(
            {
                "claim_id": f"claim-{index}",
                "task_id": f"claim-{index}",
                "section_id": f"section-{index}",
                "claim": subtask.title,
                "status": "pending",
                "claim_basis": subtask.description,
                "target_sources": _target_source_values(subtask),
                "evidence": [],
                "counter_evidence": [],
                "limitations": [],
                "open_questions": [],
                "citation_indices": [],
            }
        )
    return bundles


def build_runtime_report_context_payload(
    *,
    question: str,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, Any]:
    subtasks = list(plan_snapshot.subtasks)
    return {
        "question": question,
        "executive_summary": "",
        "confidence_level": "insufficient",
        "has_conflicts": False,
        "key_takeaways": [],
        "recommended_actions": [],
        "open_questions": [],
        "methodology_notes": [
            "先完成 claim 收口，再按 source 并行补证，最后交给 section-writer / citation 子代理统一收口。"
        ],
        "verification_notes": [],
        "coverage_focus": [
            _describe_expected_evidence(subtask) for subtask in subtasks
        ]
        or ["优先补齐高可信来源、交叉验证与反证。"],
        "section_status": [
            {
                "section_id": f"section-{index}",
                "title": subtask.title,
                "status": "pending",
                "owner": "section-writer",
            }
            for index, subtask in enumerate(subtasks, start=1)
        ],
        "citation_coverage": {
            "required_target_sources": [item.value for item in plan_snapshot.target_sources],
            "verified_count": 0,
            "pending_sections": len(subtasks),
        },
    }


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
        "current_agent_label": (
            str(first_task.get("owner") or "").strip()
            if isinstance(first_task, dict)
            else "deep-research"
        ),
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
        "status_message": "主代理正在初始化 claim/source/section 任务图。",
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
            build_runtime_claim_bundles_payload(plan_snapshot=plan_snapshot),
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
        layout.report_context_json_path: json.dumps(
            build_runtime_report_context_payload(
                question=question,
                plan_snapshot=plan_snapshot,
            ),
            ensure_ascii=False,
            indent=2,
        ),
    }
