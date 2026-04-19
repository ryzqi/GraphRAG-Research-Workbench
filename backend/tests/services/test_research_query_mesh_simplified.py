"""research_query_mesh 简化：只保留 canonical/breadth/depth。"""

from app.schemas.research import (
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
)
from app.services.research_query_mesh import build_research_query_mesh


def _plan() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot(
        research_brief="brief",
        complexity=ResearchComplexity.SIMPLE,
        summary="s",
        subtasks=[
            ResearchPlanSubtask(
                title="主要实验",
                description="HumanEval 通过率",
                target_sources=[ResearchSourceTarget.WEB],
            )
        ],
        target_sources=[ResearchSourceTarget.WEB],
    )


def test_query_mesh_contains_only_canonical_breadth_depth() -> None:
    mesh = build_research_query_mesh(question="q", plan_snapshot=_plan())
    assert mesh.canonical_query == "q"
    assert mesh.breadth_queries
    assert mesh.depth_queries
    assert not hasattr(mesh, "verification_queries")
