from __future__ import annotations

from app.schemas.research import ResearchCanonicalCitation, ResearchSourceType
from app.services.research_verification import build_verification_artifacts


def _citation(
    *,
    provider: str,
    source_id: str,
    title: str,
    origin_url: str,
) -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation(
        source_type=ResearchSourceType.WEB,
        source_provider=provider,
        retrieval_method="search",
        source_id=source_id,
        title=title,
        url=origin_url,
        origin_url=origin_url,
    )


def test_build_verification_artifacts_distinguishes_supported_contested_and_insufficient_claims() -> None:
    citations = [
        _citation(
            provider="tavily",
            source_id="openai-plan",
            title="OpenAI planner workflow",
            origin_url="https://example.com/openai-plan",
        ),
        _citation(
            provider="searxng",
            source_id="openai-workspace",
            title="OpenAI workspace execution",
            origin_url="https://example.com/openai-workspace",
        ),
        _citation(
            provider="tavily",
            source_id="claude-plan",
            title="Claude deep research planning",
            origin_url="https://example.com/claude-plan",
        ),
    ]

    artifacts = build_verification_artifacts(
        findings=[
            "OpenAI workflow 采用 planner + workspace。",
            "Claude 和 Gemini 都提供 plan-first deep research。",
            "Perplexity 支持结构化 source ledger 导出。",
        ],
        citations=citations,
        coverage_gaps=["缺少 provider 证据：Gemini"],
        provider_counts={"tavily": 2, "searxng": 1},
    )

    assert artifacts.claim_map[0]["verdict"] == "supported"
    assert artifacts.claim_map[0]["citation_indices"] == [0, 1]
    assert artifacts.claim_map[1]["verdict"] == "contested"
    assert artifacts.claim_map[1]["citation_indices"] == [2]
    assert artifacts.claim_map[2]["verdict"] == "insufficient"
    assert artifacts.claim_map[2]["citation_indices"] == []
    assert artifacts.coverage_matrix["missing_providers"] == [
        "缺少 provider 证据：Gemini"
    ]
    assert artifacts.conflicts == [
        {
            "claim": "Claude 和 Gemini 都提供 plan-first deep research。",
            "verdict": "contested",
            "reason": "coverage_gap",
            "citation_indices": [2],
            "coverage_gaps": ["缺少 provider 证据：Gemini"],
        },
        {
            "claim": "Perplexity 支持结构化 source ledger 导出。",
            "verdict": "insufficient",
            "reason": "insufficient_evidence",
            "citation_indices": [],
            "coverage_gaps": [],
        },
    ]
    assert artifacts.source_ledger[0]["provider"] == "tavily"


def test_build_verification_artifacts_does_not_mark_partially_supported_multi_subject_claim_as_supported() -> None:
    citations = [
        _citation(
            provider="tavily",
            source_id="openai-plan",
            title="OpenAI planner workflow",
            origin_url="https://example.com/openai-plan",
        ),
        _citation(
            provider="searxng",
            source_id="openai-workspace",
            title="OpenAI workspace execution",
            origin_url="https://example.com/openai-workspace",
        ),
    ]

    artifacts = build_verification_artifacts(
        findings=["OpenAI 和 Gemini 都提供 plan-first deep research。"],
        citations=citations,
        coverage_gaps=[],
        provider_counts={"tavily": 1, "searxng": 1},
    )

    assert artifacts.claim_map == [
        {
            "claim": "OpenAI 和 Gemini 都提供 plan-first deep research。",
            "verdict": "contested",
            "citation_indices": [0, 1],
        }
    ]
    assert artifacts.conflicts == [
        {
            "claim": "OpenAI 和 Gemini 都提供 plan-first deep research。",
            "verdict": "contested",
            "reason": "partial_support",
            "citation_indices": [0, 1],
            "coverage_gaps": [],
        }
    ]
