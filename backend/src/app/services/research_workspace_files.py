"""研究会话 workspace bootstrap 工件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.schemas.research import ResearchPlanSnapshot

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


def build_workspace_bootstrap_artifacts(
    *,
    session_id: UUID | str,
    question: str,
    plan_snapshot: ResearchPlanSnapshot,
) -> dict[str, ResearchArtifactSeed]:
    layout = build_research_workspace_layout(session_id)
    subtasks = "\n".join(
        f"- {item.title}: {item.description}" for item in plan_snapshot.subtasks
    ) or "- 等待 planner 生成子任务"
    return {
        "mission_md": ResearchArtifactSeed(
            artifact_key="mission_md",
            content_text=(
                "# Mission\n\n"
                f"- Session: `{layout.session_slug}`\n"
                f"- Question: {question}\n"
                f"- Brief: {plan_snapshot.research_brief}\n"
            ),
        ),
        "plan_md": ResearchArtifactSeed(
            artifact_key="plan_md",
            content_text=(
                "# Plan\n\n"
                f"## Summary\n{plan_snapshot.summary}\n\n"
                f"## Subtasks\n{subtasks}\n"
            ),
        ),
        "query_map_md": ResearchArtifactSeed(
            artifact_key="query_map_md",
            content_text="# Query Map\n\n- canonical\n- breadth\n- depth\n- verification\n",
        ),
        "coverage_md": ResearchArtifactSeed(
            artifact_key="coverage_md",
            content_text="# Coverage\n\n- status: pending\n- missing providers: []\n",
        ),
        "report_draft_md": ResearchArtifactSeed(
            artifact_key="report_draft_md",
            content_text="# Report Draft\n\n## Executive Summary\n\n研究尚未开始。\n",
        ),
    }
