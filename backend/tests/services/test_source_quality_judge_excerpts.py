"""source_quality_judge 输入必须带 excerpts，policy 改 drop on error。"""

import asyncio
from datetime import datetime, timezone

from app.config.policy_loader import load_research_policy
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchCitationExcerpt,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_source_bundle import (
    ResearchSourceQualityContext,
    ResearchSourceQualityJudge,
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
                ResearchCitationExcerpt(text="z" * 80, locator="p", lang="en")
            ],
        }
    )


def _plan_snapshot() -> ResearchPlanSnapshot:
    return ResearchPlanSnapshot.model_validate(
        {
            "research_brief": "brief",
            "complexity": ResearchComplexity.SIMPLE,
            "summary": "s",
            "subtasks": [
                ResearchPlanSubtask(
                    title="t",
                    description="d",
                    target_sources=[ResearchSourceTarget.WEB],
                ).model_dump(mode="json")
            ],
            "target_sources": [ResearchSourceTarget.WEB],
        }
    )


def test_judge_prompt_mentions_excerpt_rules() -> None:
    captured: dict[str, str] = {}

    class _FakeStructured:
        async def ainvoke(self, messages):
            captured["prompt"] = messages[0].content
            return {"raw": None, "parsed": None}

    class _FakeModel:
        def with_structured_output(self, schema, **_):
            return _FakeStructured()

    judge = ResearchSourceQualityJudge(model=_FakeModel())
    asyncio.run(
        judge.filter_citations(
            [_citation()],
            context=ResearchSourceQualityContext(
                question="q",
                plan_snapshot=_plan_snapshot(),
            ),
        )
    )
    assert "citations_json（含 excerpts）" in captured["prompt"]
    assert "excerpts 为空：一律 drop" in captured["prompt"]


def test_source_quality_policy_defaults_to_drop_on_error() -> None:
    policy = load_research_policy().source_quality
    assert policy.fallback_mode == "drop_on_judge_error"
    assert policy.keep_borderline_results is False
