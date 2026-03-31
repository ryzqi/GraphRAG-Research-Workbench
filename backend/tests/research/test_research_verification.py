from __future__ import annotations

from app.schemas.research import ResearchCanonicalCitation, ResearchSourceType
from app.services.research_verification import build_verification_artifacts


def test_build_verification_artifacts_marks_supported_and_contested_claims() -> None:
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="tavily",
            retrieval_method="search",
            source_id="source-a",
            title="A",
            url="https://example.com/a",
            origin_url="https://example.com/a",
        ),
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="searxng",
            retrieval_method="search",
            source_id="source-b",
            title="B",
            url="https://example.com/b",
            origin_url="https://example.com/b",
        ),
    ]

    artifacts = build_verification_artifacts(
        findings=[
            "OpenAI 和 Gemini 都采用计划先行的深度研究交互。",
            "Perplexity 更强调快速迭代检索与报告导出。",
        ],
        citations=citations,
        coverage_gaps=["缺少 provider 证据：jina_reader"],
        provider_counts={"tavily": 1, "searxng": 1},
    )

    assert artifacts.claim_map[0]["verdict"] == "supported"
    assert artifacts.coverage_matrix["missing_providers"] == [
        "缺少 provider 证据：jina_reader"
    ]
    assert artifacts.source_ledger[0]["provider"] == "tavily"
