"""report_compiler 从 claim/evidence JSON 渲染。"""

from datetime import datetime, timezone

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle


def _citation() -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation.model_validate(
        {
            "source_type": ResearchSourceType.WEB,
            "source_provider": "tavily",
            "retrieval_method": "web_search",
            "source_id": "https://example.com/a",
            "url": "https://example.com/a",
            "origin_url": "https://example.com/a",
            "retrieved_at": datetime.now(timezone.utc),
            "excerpts": [
                ResearchCitationExcerpt(
                    text="Claude 3.5 Sonnet 在 HumanEval 得 92%。" * 3,
                    locator="p1",
                    lang="zh",
                )
            ],
        }
    )


def test_compiler_renders_from_claim_map_json() -> None:
    bundle = ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[_citation()],
        findings=["Claude 3.5 Sonnet 在 HumanEval 上达到 92%。"],
        interim_summary="初步汇总",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )
    snapshot = ResearchRuntimeContextSnapshot(
        claim_map_json={
            "claims": [
                {
                    "claim_id": "claim-01",
                    "section_id": "section-1",
                    "claim": "Claude 3.5 Sonnet 在 HumanEval 上达到 92%。",
                    "status": "supported",
                    "confidence": "high",
                    "independence_providers": ["tavily", "arxiv"],
                    "supporting_evidence_ids": ["e-001"],
                    "counter_evidence_ids": [],
                    "limitations": [],
                    "open_questions": [],
                }
            ],
            "generated_at": "2026-04-19T00:00:00Z",
        },
        evidence_ledger_json={
            "evidences": [
                {
                    "evidence_id": "e-001",
                    "claim_ids": ["claim-01"],
                    "citation_index": 0,
                    "excerpt_ref": 0,
                    "relation": "supports",
                    "confidence": "high",
                }
            ],
            "generated_at": "2026-04-19T00:00:00Z",
        },
        report_context_json={
            "executive_summary": "Claude 3.5 Sonnet 高 pass 率。",
            "confidence_level": "sufficient",
            "has_conflicts": False,
        },
    )
    compiled = compile_report_from_runtime_context(
        question="Claude 3.5 HumanEval？",
        source_bundle=bundle,
        runtime_context_snapshot=snapshot,
    )
    assert compiled is not None
    assert "claim-01" in compiled.report_md
    assert "e-001" in compiled.report_md
    assert compiled.metadata["confidence_level"] == "sufficient"
