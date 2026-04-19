"""research_finalizer：alignment judge 集成。"""

import asyncio
from datetime import datetime, timezone

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_alignment_judge import ClaimAlignmentVerdict
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import ResearchSourceBundle


class _FakeJudge:
    async def judge_all(self, **_: object) -> list[ClaimAlignmentVerdict]:
        return [
            ClaimAlignmentVerdict(
                claim_id="claim-01",
                verdict="supported",
                supporting_evidence_ids=["e-001"],
                conflicting_evidence_ids=[],
                missing_aspects=[],
                reason="直接对应",
            )
        ]


def _citation() -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation.model_validate(
        {
            "source_type": ResearchSourceType.WEB,
            "source_provider": "tavily",
            "retrieval_method": "web_search",
            "source_id": "u1",
            "url": "https://example.com/a",
            "origin_url": "https://example.com/a",
            "retrieved_at": datetime.now(timezone.utc),
            "excerpts": [
                ResearchCitationExcerpt(text="x" * 60, locator="p", lang="en")
            ],
        }
    )


def test_finalizer_emits_alignment_pass_rate() -> None:
    bundle = ResearchSourceBundle(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[_citation()],
        findings=["Claude 3.5 在 HumanEval 达 92%。"],
        interim_summary="",
        coverage_gaps=[],
        provider_counts={"tavily": 1},
    )
    snapshot = ResearchRuntimeContextSnapshot(
        claim_map_json={
            "claims": [
                {
                    "claim_id": "claim-01",
                    "claim": "Claude 3.5 在 HumanEval 达 92%。",
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
    )
    finalizer = ResearchFinalizer(judge=_FakeJudge())
    result = asyncio.run(
        finalizer.finalize_async(
            question="q",
            target_sources=[ResearchSourceTarget.WEB],
            source_bundle=bundle,
            runtime_context_snapshot=snapshot,
        )
    )
    assert result.report_json["coverage_matrix"]["alignment_pass_rate"] == 1.0
    assert result.report_json["claim_map"][0]["verdict"] == "supported"
