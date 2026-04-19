"""research_workspace_files：新 layout 与 JSON bootstrap。"""

import json
from uuid import uuid4

from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
)
from app.schemas.research_workspace import ResearchClaimEntry
from app.services.research_workspace_files import (
    build_research_workspace_layout,
    build_runtime_claim_bundles_payload,
    build_workspace_bootstrap_artifacts,
)


def _plan() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="brief",
        complexity=ResearchComplexity.SIMPLE,
        summary="s",
        subtasks=[
            ResearchPlanSubtask(
                title="t1",
                description="d1",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
        target_sources=[ResearchSourceTarget.WEB],
    )


def test_layout_exposes_json_paths_only_for_claim_map_and_ledger() -> None:
    layout = build_research_workspace_layout(uuid4())
    assert layout.claim_map_json_path.endswith(".json")
    assert layout.evidence_ledger_json_path.endswith(".json")
    assert layout.evidence_critique_json_path.endswith("evidence-critique.json")
    assert layout.coverage_critique_json_path.endswith("coverage-critique.json")
    assert not hasattr(layout, "claim_map_md_path")
    assert not hasattr(layout, "evidence_ledger_md_path")
    assert not hasattr(layout, "analysis_notes_path")
    assert not hasattr(layout, "coverage_path")
    assert not hasattr(layout, "query_map_path")


def test_bootstrap_artifacts_contain_json_initializers() -> None:
    plan = _plan()
    seeds = build_workspace_bootstrap_artifacts(
        session_id=uuid4(),
        question="q",
        plan_snapshot=plan,
    )
    assert "claim_map_json" in seeds
    assert "evidence_ledger_json" in seeds
    assert "mission_md" in seeds
    assert "plan_md" in seeds
    claim_map_seed = json.loads(seeds["claim_map_json"].content_text)
    evidence_seed = json.loads(seeds["evidence_ledger_json"].content_text)
    assert claim_map_seed["claims"] == []
    assert evidence_seed["evidences"] == []
    assert seeds.get("claim_map_md") is None
    assert seeds.get("analysis_notes_md") is None
    assert seeds.get("coverage_md") is None
    assert seeds.get("query_map_md") is None


def test_claim_bundles_match_claim_entry_schema() -> None:
    bundles = build_runtime_claim_bundles_payload(plan_snapshot=_plan())
    entries = [ResearchClaimEntry.model_validate(item) for item in bundles]
    assert [entry.claim_id for entry in entries] == ["claim-01"]
