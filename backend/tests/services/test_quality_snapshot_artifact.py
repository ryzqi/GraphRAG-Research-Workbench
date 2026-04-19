"""quality_snapshot artifact 落盘。"""

import pytest

from app.services.research_observability import build_quality_snapshot


def test_quality_snapshot_contains_required_metrics() -> None:
    snapshot = build_quality_snapshot(
        claim_map=[
            {"verdict": "supported", "missing_aspects": []},
            {"verdict": "supported", "missing_aspects": []},
            {"verdict": "insufficient", "missing_aspects": ["x"]},
        ],
        citations=[
            {"excerpts": [{"text": "a" * 80}]},
            {"excerpts": [{"text": "b" * 80}]},
            {"excerpts": []},
        ],
        findings=[
            {"independent_providers": ["tavily", "arxiv"], "counter_searched": True},
            {"independent_providers": ["tavily"], "counter_searched": False},
        ],
        orphan_citation_indices=[2],
    )
    assert snapshot["claim_alignment_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert snapshot["citation_excerpt_presence"] == pytest.approx(2 / 3, rel=1e-3)
    assert snapshot["independence_source_ratio"] == 0.5
    assert snapshot["counter_evidence_exposure"] == 0.5
    assert snapshot["citation_orphan_rate"] == pytest.approx(1 / 3, rel=1e-3)
