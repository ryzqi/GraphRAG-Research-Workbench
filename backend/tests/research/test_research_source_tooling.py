from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import app.services.deep_research_runtime as runtime_module
from pydantic import BaseModel
from app.agents.tool_calling.registry import build_research_tool_registry
from app.core.settings import Settings
from app.schemas.research import ResearchCanonicalCitation, ResearchSourceTarget, ResearchSourceType
from app.services.deep_research_runtime import (
    create_deep_research_runtime,
    resolve_source_subagent_route,
)
from app.services.research_finalizer import ResearchFinalizer
from app.services.research_runtime_types import (
    ResearchRuntimeConfig,
    ResearchToolRegistryBundle,
)
from app.services.research_source_bundle import ResearchSourceBundleBuilder


async def test_build_research_tool_registry_exposes_provider_specific_tools_without_mcp() -> None:
    settings = Settings(
        web_search_api_key="test-key",
        jina_read_enabled=True,
        searxng_search_enabled=True,
        mcp_enabled=True,
    )

    bundle = await build_research_tool_registry(settings=settings)

    tool_names = {tool.name for tool in bundle.tools}
    assert {
        "tavily_search",
        "tavily_extract",
        "tavily_crawl",
        "tavily_research",
        "jina_read",
        "searxng_search",
        "arxiv_search",
        "arxiv_fetch",
    }.issubset(tool_names)
    assert "web_search" not in tool_names
    assert not any(name.startswith("mcp__") for name in bundle.tool_meta_by_name)
    assert bundle.tool_groups["web"] == (
        "tavily_search",
        "tavily_extract",
        "tavily_crawl",
        "tavily_research",
        "jina_read",
        "searxng_search",
    )
    assert bundle.tool_groups["paper"] == ("arxiv_search", "arxiv_fetch")


async def test_create_deep_research_runtime_builds_source_specialized_subagents() -> None:
    captured: dict[str, Any] = {}

    registry_bundle = ResearchToolRegistryBundle(
        tools=[
            SimpleNamespace(name="tavily_search"),
            SimpleNamespace(name="jina_read"),
            SimpleNamespace(name="searxng_search"),
            SimpleNamespace(name="arxiv_search"),
            SimpleNamespace(name="arxiv_fetch"),
        ],
        tool_meta_by_name={},
        tool_groups={
            "web": (
                "tavily_search",
                "jina_read",
                "searxng_search",
            ),
            "paper": ("arxiv_search", "arxiv_fetch"),
            "citation": (),
        },
    )

    async def fake_build_research_tool_registry(**_: Any) -> ResearchToolRegistryBundle:
        return registry_bundle

    def fake_create_deep_agent(**kwargs: Any) -> str:
        captured["agent_kwargs"] = kwargs
        return "deep-agent-sentinel"

    original_build_research_tool_registry = runtime_module.build_research_tool_registry
    original_create_deep_agent = runtime_module.create_deep_agent
    runtime_module.build_research_tool_registry = fake_build_research_tool_registry  # type: ignore[assignment]
    runtime_module.create_deep_agent = fake_create_deep_agent  # type: ignore[assignment]
    try:
        config = ResearchRuntimeConfig(
            primary_model="gpt-5.2",
            subagent_model="gpt-5.2-mini",
            finalizer_model="gpt-5.2",
            system_prompt="你是深度研究助手。",
        )
        await create_deep_research_runtime(
            settings=cast(Any, object()),
            config=config,
            checkpointer=object(),
            store=object(),
        )
    finally:
        runtime_module.build_research_tool_registry = original_build_research_tool_registry  # type: ignore[assignment]
        runtime_module.create_deep_agent = original_create_deep_agent  # type: ignore[assignment]

    subagents = captured["agent_kwargs"]["subagents"]
    assert [subagent["name"] for subagent in subagents] == [
        "general-purpose",
        "web",
        "paper",
        "citation",
    ]
    assert [tool.name for tool in subagents[1]["tools"]] == [
        "tavily_search",
        "jina_read",
        "searxng_search",
    ]
    assert [tool.name for tool in subagents[2]["tools"]] == [
        "arxiv_search",
        "arxiv_fetch",
    ]
    assert subagents[3]["model"] == "gpt-5.2"


def test_resolve_source_subagent_route_handles_web_and_paper() -> None:
    assert resolve_source_subagent_route((ResearchSourceTarget.WEB,)) == (
        "web",
        "citation",
    )
    assert resolve_source_subagent_route((ResearchSourceTarget.PAPER,)) == (
        "paper",
        "citation",
    )
    assert resolve_source_subagent_route((ResearchSourceTarget.PAPER, ResearchSourceTarget.WEB)) == (
        "paper",
        "web",
        "citation",
    )


def test_source_bundle_builder_dedupes_origin_url_and_emits_provider_gaps() -> None:
    builder = ResearchSourceBundleBuilder()
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="jina_reader",
            retrieval_method="read",
            source_id="https://r.jina.ai/http://example.com/article-a",
            title="Article A",
            url="https://r.jina.ai/http://example.com/article-a",
            origin_url="https://example.com/article-a",
        ),
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="tavily",
            retrieval_method="search",
            source_id="https://example.com/article-a",
            title="Article A",
            url="https://example.com/article-a",
            origin_url="https://example.com/article-a",
        ),
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.PAPER,
            source_provider="arxiv",
            retrieval_method="fetch",
            source_id="arxiv:2501.00001",
            title="Paper A",
            url="https://arxiv.org/abs/2501.00001",
            origin_url="https://arxiv.org/abs/2501.00001",
            arxiv_id="2501.00001",
            authors=["Alice"],
            pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
        ),
    ]

    bundle = builder.build(
        target_sources=(ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER),
        citations=citations,
        findings=[
            "Article A 解释了当前网页 provider 的上下文读取差异。",
            "Paper A 给出了研究代理设计的论文基线。",
        ],
        required_web_providers=("tavily", "jina_reader", "searxng"),
    )

    assert len(bundle.citations) == 2
    assert bundle.citations[0].origin_url == "https://example.com/article-a"
    assert bundle.coverage_gaps == ["缺少 provider 证据：searxng"]
    assert "2 条去重证据" in bundle.interim_summary


def test_source_bundle_builder_reports_missing_provider_gaps_for_comparative_plan() -> None:
    builder = ResearchSourceBundleBuilder()
    citations = [
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="tavily",
            retrieval_method="search",
            source_id="https://example.com/tavily",
            title="Tavily Result",
            url="https://example.com/tavily",
            origin_url="https://example.com/tavily",
        ),
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.WEB,
            source_provider="jina_reader",
            retrieval_method="read",
            source_id="https://r.jina.ai/http://example.com/jina",
            title="Jina Result",
            url="https://r.jina.ai/http://example.com/jina",
            origin_url="https://example.com/jina",
        ),
        ResearchCanonicalCitation(
            source_type=ResearchSourceType.PAPER,
            source_provider="arxiv",
            retrieval_method="fetch",
            source_id="arxiv:2501.00001",
            title="Paper A",
            url="https://arxiv.org/abs/2501.00001",
            origin_url="https://arxiv.org/abs/2501.00001",
            arxiv_id="2501.00001",
            pdf_url="https://arxiv.org/pdf/2501.00001.pdf",
        ),
    ]
    findings = [
        "Tavily 适合广度搜索。",
        "Jina Reader 适合正文读取。",
        "论文证据可作为复杂研究的补充锚点。",
    ]

    bundle = builder.build(
        target_sources=(ResearchSourceTarget.WEB, ResearchSourceTarget.PAPER),
        citations=citations,
        findings=findings,
        required_web_providers=("tavily", "jina_reader", "searxng"),
    )

    assert "缺少 provider 证据：searxng" in bundle.coverage_gaps


def test_research_finalizer_outputs_report_md_and_report_json() -> None:
    class _ReportPayload(BaseModel):
        question: str
        target_sources: list[str]
        summary: str
        findings: list[str]
        coverage_gaps: list[str]
        provider_counts: dict[str, int]
        citations: list[dict[str, Any]]
        report_md: str

    citation = ResearchCanonicalCitation(
        source_type=ResearchSourceType.WEB,
        source_provider="jina_reader",
        retrieval_method="read",
        source_id="https://r.jina.ai/http://example.com/article-a",
        title="Article A",
        url="https://r.jina.ai/http://example.com/article-a",
        origin_url="https://example.com/article-a",
    )
    bundle = ResearchSourceBundleBuilder().build(
        target_sources=(ResearchSourceTarget.WEB,),
        citations=[citation],
        findings=["Article A 解释了 Jina Reader 只应作为读取通道，不应污染最终引用 URL。"],
        required_web_providers=("jina_reader",),
    )

    result = ResearchFinalizer().finalize(
        question="解释 Jina Reader 在深度研究中的引用约束",
        target_sources=(ResearchSourceTarget.WEB,),
        source_bundle=bundle,
        response_format=_ReportPayload,
    )

    assert result.report_json["question"] == "解释 Jina Reader 在深度研究中的引用约束"
    assert result.report_json["citations"][0]["origin_url"] == "https://example.com/article-a"
    assert "Article A" in result.report_md
    assert "https://r.jina.ai/" not in result.report_md
