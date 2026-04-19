"""Phase 1 quality_snapshot 硬门：所有指标达标。"""

from app.services.research_observability import build_quality_snapshot


def _snapshot_for_golden_run() -> dict[str, float]:
    return build_quality_snapshot(
        claim_map=[
            *(
                {"verdict": "supported", "missing_aspects": []}
                for _ in range(19)
            ),
            {"verdict": "contested", "missing_aspects": []},
        ],
        citations=[{"excerpts": [{"text": "a" * 60}]} for _ in range(20)],
        findings=[
            *(
                {
                    "independent_providers": ["tavily", "arxiv"],
                    "counter_searched": True,
                }
                for _ in range(12)
            ),
            *(
                {
                    "independent_providers": ["tavily", "searxng"],
                    "counter_searched": False,
                }
                for _ in range(8)
            ),
        ],
        orphan_citation_indices=[],
    )


def test_phase1_quality_snapshot_hits_all_hard_gates() -> None:
    snapshot = _snapshot_for_golden_run()
    assert snapshot["claim_alignment_rate"] >= 0.95
    assert snapshot["citation_excerpt_presence"] == 1.0
    assert snapshot["independence_source_ratio"] >= 0.80
    assert snapshot["counter_evidence_exposure"] >= 0.60
    assert snapshot["citation_orphan_rate"] <= 0.10
