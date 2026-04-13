from __future__ import annotations

from types import SimpleNamespace

from langchain_core.documents import Document

import app.search.web.enrichment as enrichment
import app.search.web.fusion as fusion
import app.search.web.rerank as rerank
import app.services.research_query_mesh as research_query_mesh
import app.services.web_search_status_service as web_search_status_service
from app.config.policy_models import ResearchPolicy, SearchPolicy
from app.core.settings import Settings
from app.schemas.chats import WebSearchStatusRead
from app.schemas.research import ResearchSourceTarget
from app.search.web.documents import build_document


def _build_search_policy() -> SearchPolicy:
    return SearchPolicy.model_validate(
        {
            "version": "test",
            "query_rewrite": {
                "freshness_keywords": ["latest"],
                "auto_include_domains": {
                    "langchain": ["docs.langchain.com"],
                },
                "append_current_year_suffix": True,
            },
            "fusion": {
                "rrf_k": 10,
                "provider_weights": {
                    "tavily": 0.1,
                    "searxng": 2.0,
                },
            },
            "rerank": {
                "high_authority_domain_suffixes": ["trusted.example"],
                "low_quality_domain_suffixes": ["noise.example"],
                "overlap_bonus_weight": 0.9,
                "lexical_bonus_per_term": 0.01,
                "authority_bonus": 1.0,
                "freshness_bonus": 0.0,
                "social_penalty": 2.0,
                "enriched_bonus": 0.0,
            },
            "enrichment": {
                "low_quality_domain_suffixes": [
                    "noise.example",
                    "spam.example",
                ],
                "snippet_min_length": 10,
                "top_k": 1,
            },
            "query_planning": {
                "default_clarification_question": "请补充问题对象。",
                "default_ambiguity_true_reason": "需要澄清。",
                "default_ambiguity_false_reason": "可以继续。",
                "ambiguity_reason_labels": {
                    "missing_entity": "对象缺失",
                    "missing_scope": "范围缺失",
                    "missing_time": "时间缺失",
                    "missing_metric": "指标缺失",
                    "coref_uncertain": "指代不明",
                    "mixed": "信息不完整",
                },
                "default_complexity_direct_reason": "走 direct",
                "default_complexity_multi_query_reason": "走 multi-query",
                "default_complexity_decomposition_reason": "走 decomposition",
                "guardrail_complexity_direct_reason": "guardrail direct",
                "guardrail_complexity_decomposition_reason": "guardrail decomposition",
                "multi_query_label_tokens": ["AlphaTag"],
                "troubleshoot_keywords": ["paniccode"],
                "coref_markers_zh": ["这个"],
                "coref_markers_en": ["this"],
                "compare_keywords": ["compare", "比较"],
                "multi_target_separators": [" 和 ", ","],
                "term_alias_keywords": ["别名", "alias"],
                "taxonomy_query_keywords": ["分类"],
                "stable_overview_ask_markers": ["是什么"],
                "taxonomy_ask_markers": ["是什么"],
                "taxonomy_drift_keywords": ["性能"],
                "stable_overview_keywords": ["核心组件"],
                "multi_entity_signal_keywords": ["分别"],
                "question_dimension_keywords": {
                    "技术架构": ["技术架构"],
                },
                "decomposition_max_sub_queries": 5,
                "multi_query_fixed_variants": 3,
                "hyde_num_hypotheses": 5,
                "hyde_aggregation": "mean_embedding",
                "hyde_regenerate_on_retry": True,
                "structured_call_max_attempts": 2,
                "structured_call_retryable_reasons": [
                    "error",
                    "empty_structured_response",
                    "invalid_schema",
                ],
            },
        }
    )


def _build_research_policy(*, cache_ttl_seconds: float = 5.0) -> ResearchPolicy:
    return ResearchPolicy.model_validate(
        {
            "version": "test",
            "coverage_gate": {
                "default_required_web_providers": ["tavily"],
                "required_web_provider_counts": {
                    "simple": 1,
                    "comparative": 1,
                    "complex": 1,
                },
                "required_unique_source_counts": {
                    "simple": 2,
                    "comparative": 2,
                    "complex": 2,
                },
            },
            "status_probe": {
                "cache_ttl_seconds": cache_ttl_seconds,
                "provider_order": ["tavily", "jina_reader"],
                "search_provider_names": ["tavily"],
                "search_probe_query": "policy probe query",
                "jina_probe_url": "https://probe.example.com/health",
            },
        }
    )


def test_fusion_uses_policy_weights(monkeypatch) -> None:
    policy = _build_search_policy()
    monkeypatch.setattr(fusion, "load_search_policy", lambda: policy)

    results = fusion.fuse_documents(
        [
            [
                build_document(
                    provider="tavily",
                    provider_rank=1,
                    query="q",
                    title="A",
                    url="https://example.com/a",
                    snippet="A",
                )
            ],
            [
                build_document(
                    provider="searxng",
                    provider_rank=1,
                    query="q",
                    title="B",
                    url="https://example.com/b",
                    snippet="B",
                )
            ],
        ],
        max_results=2,
    )

    assert [item.metadata["provider"] for item in results] == ["searxng", "tavily"]


def test_rerank_uses_policy_authority_and_penalty_weights(monkeypatch) -> None:
    policy = _build_search_policy()
    monkeypatch.setattr(rerank, "load_search_policy", lambda: policy)

    results = rerank.rerank_documents(
        [
            Document(
                page_content="latest release notes",
                metadata={
                    "title": "Trusted result",
                    "url": "https://docs.trusted.example/guide",
                    "domain": "docs.trusted.example",
                    "fusion_score": 0.2,
                    "overlap_count": 1,
                    "enriched": False,
                    "published_at": None,
                },
            ),
            Document(
                page_content="latest release notes",
                metadata={
                    "title": "Noisy result",
                    "url": "https://feed.noise.example/post",
                    "domain": "feed.noise.example",
                    "fusion_score": 0.8,
                    "overlap_count": 1,
                    "enriched": False,
                    "published_at": None,
                },
            ),
        ],
        query="latest release",
        max_results=2,
    )

    assert results[0].metadata["domain"] == "docs.trusted.example"


async def test_enrichment_uses_policy_domains_and_default_top_k(monkeypatch) -> None:
    policy = _build_search_policy()
    monkeypatch.setattr(enrichment, "load_search_policy", lambda: policy)

    class FakeReadProvider:
        provider_name = "jina_reader"

        def __init__(self) -> None:
            self.urls: list[str] = []

        async def read(self, *, url: str) -> dict[str, object]:
            self.urls.append(url)
            return {
                "title": "补读标题",
                "content": f"enriched:{url}",
            }

    read_provider = FakeReadProvider()
    documents = [
        Document(
            page_content="x" * 200,
            metadata={
                "provider": "tavily",
                "provider_rank": 1,
                "url": "https://foo.noise.example/a",
                "domain": "foo.noise.example",
            },
        ),
        Document(
            page_content="y" * 200,
            metadata={
                "provider": "searxng",
                "provider_rank": 1,
                "url": "https://bar.spam.example/b",
                "domain": "bar.spam.example",
            },
        ),
    ]

    enriched_documents, report = await enrichment.enrich_documents(
        documents,
        read_provider=read_provider,
    )

    assert read_provider.urls == ["https://foo.noise.example/a"]
    assert enriched_documents[0].page_content == "enriched:https://foo.noise.example/a"
    assert enriched_documents[1].page_content == "y" * 200
    assert report is not None
    assert report["result_count"] == 1


def test_research_query_mesh_uses_policy_thresholds(monkeypatch) -> None:
    policy = _build_research_policy()
    monkeypatch.setattr(research_query_mesh, "load_research_policy", lambda: policy)

    result = research_query_mesh.evaluate_coverage_gate(
        complexity="simple",
        provider_counts={"tavily": 1},
        unique_source_count=2,
        source_types={"web"},
        target_sources={ResearchSourceTarget.WEB},
    )

    assert result.passed is True
    assert result.reasons == ()

    required = research_query_mesh.select_required_web_providers(
        complexity="simple",
        available_providers=["custom-web"],
    )
    assert required == ("tavily", "custom-web")


async def test_web_search_status_uses_policy_cache_ttl_and_probe_contract(
    monkeypatch,
) -> None:
    policy = _build_research_policy(cache_ttl_seconds=1.0)
    monkeypatch.setattr(
        web_search_status_service,
        "load_research_policy",
        lambda: policy,
        raising=False,
    )

    probe_calls = {"count": 0}
    monotonic_values = [0.0, 0.0, 0.0, 0.2, 1.5, 1.5, 1.5]
    last_monotonic = {"value": monotonic_values[-1]}

    async def fake_probe_web_search_status(*, settings: Settings) -> WebSearchStatusRead:
        probe_calls["count"] += 1
        return WebSearchStatusRead(
            configured=True,
            verified=True,
            mode="healthy",
            providers=[],
        )

    def fake_monotonic() -> float:
        if monotonic_values:
            last_monotonic["value"] = monotonic_values.pop(0)
        return float(last_monotonic["value"])

    monkeypatch.setattr(
        web_search_status_service,
        "_probe_web_search_status",
        fake_probe_web_search_status,
    )
    monkeypatch.setattr(web_search_status_service, "_monotonic", fake_monotonic)

    web_search_status_service._cached_status = None
    web_search_status_service._cached_expires_at = 0.0

    settings = Settings(_env_file=None)
    await web_search_status_service.get_web_search_status(settings=settings)
    await web_search_status_service.get_web_search_status(settings=settings)
    await web_search_status_service.get_web_search_status(settings=settings)

    assert probe_calls["count"] == 2

    captured_query: dict[str, str] = {}
    captured_url: dict[str, str] = {}

    class FakeSearchProvider:
        provider_name = "tavily"

        async def search(self, **kwargs):
            captured_query["value"] = kwargs["query"]
            return SimpleNamespace(
                report=SimpleNamespace(
                    ok=True,
                    error=None,
                )
            )

    class FakeJinaReadProvider:
        def __init__(self, *, settings: Settings) -> None:
            self._settings = settings

        async def read(self, *, url: str) -> dict[str, object]:
            captured_url["value"] = url
            return {
                "title": "probe",
                "content": "probe ok",
            }

    monkeypatch.setattr(
        web_search_status_service,
        "has_jina_read_provider",
        lambda settings: True,
    )
    monkeypatch.setattr(
        web_search_status_service,
        "JinaReadProvider",
        FakeJinaReadProvider,
    )

    await web_search_status_service._probe_search_provider(FakeSearchProvider())
    await web_search_status_service._probe_jina_read_provider(settings=settings)

    assert captured_query["value"] == "policy probe query"
    assert captured_url["value"] == "https://probe.example.com/health"
