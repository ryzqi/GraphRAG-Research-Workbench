import json
import uuid

from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
)
from app.services.research_workspace_files import (
    build_runtime_claim_bundles_payload,
    build_runtime_task_graph_payload,
    build_workspace_bootstrap_artifacts,
)


def _build_plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        summary="对比 Responses API 与 Chat Completions API",
        complexity=ResearchComplexity.COMPARATIVE,
        research_brief="比较两类 API 的定位、能力边界与适用场景。",
        target_sources=[ResearchSourceTarget.WEB],
        budget_guidance="优先使用官方网页来源。",
        subtasks=[
            ResearchPlanSubtask(
                title="定位差异",
                description="比较两类 API 的设计定位。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
            ResearchPlanSubtask(
                title="能力边界",
                description="比较两类 API 的能力边界。",
                target_sources=[ResearchSourceTarget.WEB],
            ),
        ],
    )


def test_workspace_bootstrap_claim_map_seeds_pending_claims() -> None:
    plan_snapshot = _build_plan_snapshot()

    artifacts = build_workspace_bootstrap_artifacts(
        session_id=uuid.uuid4(),
        question="比较 Responses API 与 Chat Completions API",
        plan_snapshot=plan_snapshot,
    )

    claim_map_text = artifacts["claim_map_json"].content_text
    assert isinstance(claim_map_text, str) and claim_map_text

    claim_map = json.loads(claim_map_text)
    claims = claim_map["claims"]

    assert [item["claim_id"] for item in claims] == ["claim-01", "claim-02"]
    assert [item["section_id"] for item in claims] == ["section-1", "section-2"]
    assert [item["claim"] for item in claims] == ["定位差异", "能力边界"]
    assert all(item["status"] == "pending" for item in claims)
    assert all(item["supporting_evidence_ids"] == [] for item in claims)
    assert all(item["counter_evidence_ids"] == [] for item in claims)


def test_runtime_scaffold_claim_ids_stay_consistent() -> None:
    plan_snapshot = _build_plan_snapshot()

    claim_bundles = build_runtime_claim_bundles_payload(plan_snapshot=plan_snapshot)
    task_graph = build_runtime_task_graph_payload(
        question="比较 Responses API 与 Chat Completions API",
        plan_snapshot=plan_snapshot,
    )

    bundle_claim_ids = [item["claim_id"] for item in claim_bundles]
    task_claim_ids = [
        item["claim_id"]
        for item in task_graph["tasks"]
        if item.get("task_kind") == "claim"
    ]

    assert bundle_claim_ids == ["claim-01", "claim-02"]
    assert task_claim_ids == bundle_claim_ids
