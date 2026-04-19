from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(slots=True, frozen=True)
class ResearchRuntimeBackendRoots:
    workspace_root: str = "/workspace/"
    scratch_root: str = "/scratch/"
    plans_root: str = "/plans/"
    memories_root: str = "/memories/"
    skills_root: str = "/skills/"

    def workspace_session_root(self, session_slug: str) -> str:
        return f"{self.workspace_root.rstrip('/')}/research/{session_slug}"

    def scratch_session_root(self, session_slug: str) -> str:
        return f"{self.scratch_root.rstrip('/')}/research/{session_slug}"


@dataclass(slots=True, frozen=True)
class ResearchRuntimeRequestContext:
    context_root: str = "/workspace/context"
    guide_filename: str = "runtime_context_guide.md"
    session_question_filename: str = "session_question.txt"
    plan_snapshot_filename: str = "plan_snapshot.json"
    query_mesh_filename: str = "query_mesh.json"
    clarification_context_filename: str = "clarification_context.md"

    @property
    def guide_path(self) -> str:
        return f"{self.context_root}/{self.guide_filename}"

    @property
    def session_question_path(self) -> str:
        return f"{self.context_root}/{self.session_question_filename}"

    @property
    def plan_snapshot_path(self) -> str:
        return f"{self.context_root}/{self.plan_snapshot_filename}"

    @property
    def query_mesh_path(self) -> str:
        return f"{self.context_root}/{self.query_mesh_filename}"

    @property
    def clarification_context_path(self) -> str:
        return f"{self.context_root}/{self.clarification_context_filename}"

    @property
    def request_paths(self) -> tuple[str, ...]:
        return (
            self.session_question_path,
            self.plan_snapshot_path,
            self.query_mesh_path,
            self.clarification_context_path,
        )


@dataclass(slots=True, frozen=True)
class ResearchRuntimeLayoutManifest:
    mission_relative_path: str = "00-mission.md"
    plan_relative_path: str = "01-plan.md"
    report_draft_relative_path: str = "02-report-draft.md"
    report_outline_relative_path: str = "03-report-outline.md"
    claim_map_json_relative_path: str = "04-claim-map.json"
    evidence_ledger_json_relative_path: str = "05-evidence-ledger.json"
    task_graph_relative_path: str = "06-task-graph.json"
    claim_bundles_relative_path: str = "07-claim-bundles.json"
    section_briefs_relative_path: str = "08-section-briefs.json"
    live_board_relative_path: str = "09-live-board.json"
    report_context_relative_path: str = "report/report-context.json"
    evidence_critique_relative_path: str = "critique/evidence-critique.json"
    coverage_critique_relative_path: str = "critique/coverage-critique.json"
    bootstrap_artifact_key_to_attr: tuple[tuple[str, str], ...] = (
        ("mission_md", "mission_path"),
        ("plan_md", "plan_path"),
        ("report_draft_md", "report_draft_path"),
        ("report_outline_md", "report_outline_path"),
        ("claim_map_json", "claim_map_json_path"),
        ("evidence_ledger_json", "evidence_ledger_json_path"),
        ("task_graph_json", "task_graph_path"),
        ("claim_bundles_json", "claim_bundles_path"),
        ("section_briefs_json", "section_briefs_path"),
        ("live_board_json", "live_board_path"),
    )
    priority_layout_attrs: tuple[str, ...] = (
        "mission_path",
        "plan_path",
        "claim_map_json_path",
        "evidence_ledger_json_path",
        "claim_bundles_path",
        "section_briefs_path",
        "report_context_json_path",
        "task_graph_path",
    )
    snapshot_layout_attrs: tuple[str, ...] = (
        "claim_map_json_path",
        "evidence_ledger_json_path",
        "claim_bundles_path",
        "section_briefs_path",
        "report_outline_path",
        "report_draft_path",
        "report_context_json_path",
        "task_graph_path",
        "live_board_path",
        "evidence_critique_json_path",
        "coverage_critique_json_path",
    )
    analysis_layout_attrs: tuple[str, ...] = (
        "claim_map_json_path",
        "evidence_ledger_json_path",
        "report_outline_path",
        "report_draft_path",
    )
    projection_layout_attrs: tuple[str, ...] = ("live_board_path",)


@dataclass(slots=True, frozen=True)
class ResearchRuntimeWorkspaceContextDoc:
    virtual_path: str
    disk_path: Path


RESEARCH_RUNTIME_BACKEND_ROOTS = ResearchRuntimeBackendRoots()
RESEARCH_RUNTIME_REQUEST_CONTEXT = ResearchRuntimeRequestContext()
RESEARCH_RUNTIME_LAYOUT_MANIFEST = ResearchRuntimeLayoutManifest()
DEFAULT_RESEARCH_RUNTIME_MEMORY_PATH = (
    f"{RESEARCH_RUNTIME_BACKEND_ROOTS.memories_root.rstrip('/')}/"
    "deep-research/runtime-memory.md"
)
RESEARCH_RUNTIME_WORKSPACE_CONTEXT_DOCS: tuple[
    ResearchRuntimeWorkspaceContextDoc, ...
] = (
    ResearchRuntimeWorkspaceContextDoc(
        virtual_path=f"{RESEARCH_RUNTIME_REQUEST_CONTEXT.context_root}/api_contract_research.md",
        disk_path=_REPO_ROOT / "docs" / "api_contract_research.md",
    ),
    ResearchRuntimeWorkspaceContextDoc(
        virtual_path=f"{RESEARCH_RUNTIME_REQUEST_CONTEXT.context_root}/research_design.md",
        disk_path=_REPO_ROOT / "full-refactor-deep-research" / "design.md",
    ),
    ResearchRuntimeWorkspaceContextDoc(
        virtual_path=f"{RESEARCH_RUNTIME_REQUEST_CONTEXT.context_root}/research_readme.md",
        disk_path=_REPO_ROOT / "README.md",
    ),
)
