"""research_alignment_judge：LLM 对齐裁决。"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchSourceType,
)
from app.schemas.research_workspace import (
    ResearchClaimEntry,
    ResearchEvidenceEntry,
)
from app.services.research_alignment_judge import (
    ClaimAlignmentJudgeOutput,
    ResearchAlignmentJudge,
)


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
                    text="Claude 3.5 Sonnet achieves 92% pass@1 on HumanEval benchmark.",
                    locator="section-eval",
                    lang="en",
                )
            ],
        }
    )


def _claim() -> ResearchClaimEntry:
    return ResearchClaimEntry.model_validate(
        {
            "claim_id": "claim-01",
            "section_id": "section-1",
            "claim": "Claude 3.5 Sonnet 在 HumanEval 上达到 92% 通过率。",
            "status": "pending",
            "confidence": "medium",
            "independence_providers": ["tavily"],
            "supporting_evidence_ids": ["e-001"],
            "counter_evidence_ids": [],
            "limitations": [],
            "open_questions": [],
        }
    )


def _evidence() -> ResearchEvidenceEntry:
    return ResearchEvidenceEntry.model_validate(
        {
            "evidence_id": "e-001",
            "claim_ids": ["claim-01"],
            "citation_index": 0,
            "excerpt_ref": 0,
            "relation": "supports",
            "confidence": "high",
        }
    )


def test_alignment_judge_routes_to_llm_and_parses_output() -> None:
    fake_output = ClaimAlignmentJudgeOutput.model_validate(
        {
            "results": [
                {
                    "claim_id": "claim-01",
                    "verdict": "supported",
                    "supporting_evidence_ids": ["e-001"],
                    "conflicting_evidence_ids": [],
                    "missing_aspects": [],
                    "reason": "原文出现 92% HumanEval 数据",
                }
            ]
        }
    )

    class _FakeStructured:
        async def ainvoke(self, messages: Any) -> Any:
            return {"raw": None, "parsed": fake_output}

    class _FakeModel:
        def with_structured_output(self, schema: Any, **_: Any) -> Any:
            return _FakeStructured()

    judge = ResearchAlignmentJudge(
        model=_FakeModel(), structured_method="function_calling"
    )
    outputs = asyncio.run(
        judge.judge_batch(
            claims=[_claim()],
            evidences=[_evidence()],
            citations=[_citation()],
        )
    )
    assert outputs.results[0].verdict == "supported"


def test_alignment_judge_batches_respect_limit() -> None:
    judge = ResearchAlignmentJudge(model=None, structured_method="function_calling")
    batches = list(judge.split_into_batches(list(range(10)), batch_size=4))
    assert [len(b) for b in batches] == [4, 4, 2]
