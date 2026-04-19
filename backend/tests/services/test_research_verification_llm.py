"""research_verification：LLM 版。"""

import asyncio
from datetime import datetime, timezone

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchSourceType,
)
from app.schemas.research_workspace import (
    ResearchClaimEntry,
    ResearchEvidenceEntry,
)
from app.services.research_alignment_judge import ClaimAlignmentVerdict
from app.services.research_verification import build_verification_artifacts_async


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
                    text="Claude 3.5 Sonnet 在 HumanEval 上得到了 92% 的通过率。",
                    locator="para-3",
                    lang="zh",
                )
            ],
        }
    )


class _FakeJudge:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict

    async def judge_all(self, **_: object) -> list[ClaimAlignmentVerdict]:
        return [
            ClaimAlignmentVerdict(
                claim_id="claim-01",
                verdict=self._verdict,
                supporting_evidence_ids=["e-001"]
                if self._verdict == "supported"
                else [],
                conflicting_evidence_ids=[],
                missing_aspects=[] if self._verdict == "supported" else ["92%"],
                reason="测试",
            )
        ]


def _fixtures() -> tuple[ResearchClaimEntry, ResearchEvidenceEntry]:
    claim = ResearchClaimEntry.model_validate(
        {
            "claim_id": "claim-01",
            "section_id": "section-1",
            "claim": "Claude 3.5 Sonnet 在 HumanEval 上达到 92% 通过率。",
            "status": "pending",
            "confidence": "medium",
        }
    )
    evidence = ResearchEvidenceEntry.model_validate(
        {
            "evidence_id": "e-001",
            "claim_ids": ["claim-01"],
            "citation_index": 0,
            "excerpt_ref": 0,
            "relation": "supports",
            "confidence": "high",
        }
    )
    return claim, evidence


def test_verification_supported_when_judge_says_supported() -> None:
    claim, evidence = _fixtures()
    artifacts = asyncio.run(
        build_verification_artifacts_async(
            claims=[claim],
            evidences=[evidence],
            citations=[_citation()],
            coverage_gaps=[],
            provider_counts={"tavily": 1},
            judge=_FakeJudge("supported"),
        )
    )
    assert artifacts.claim_map[0]["verdict"] == "supported"
    assert not artifacts.conflicts


def test_verification_insufficient_when_missing_aspects() -> None:
    claim, evidence = _fixtures()
    artifacts = asyncio.run(
        build_verification_artifacts_async(
            claims=[claim],
            evidences=[evidence],
            citations=[_citation()],
            coverage_gaps=[],
            provider_counts={"tavily": 1},
            judge=_FakeJudge("insufficient"),
        )
    )
    assert artifacts.claim_map[0]["verdict"] == "insufficient"
    assert artifacts.conflicts
    assert artifacts.conflicts[0]["reason"] == "insufficient_evidence"
