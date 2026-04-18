from __future__ import annotations

import app.services.research_source_bundle as source_bundle_module
import pytest
from app.config.policy_loader import load_research_policy
from app.config.policy_provider import PolicyProvider
from app.schemas.research import (
    ResearchCanonicalCitation,
    ResearchComplexity,
    ResearchPlanSnapshot,
    ResearchPlanSubtask,
    ResearchSourceTarget,
    ResearchSourceType,
)
from app.services.research_query_mesh import build_research_query_mesh
from app.services.research_report_compiler import compile_report_from_runtime_context
from app.services.research_runtime_context import ResearchRuntimeContextSnapshot
from app.services.research_source_bundle import (
    ResearchSourceBundleBuilder,
    ResearchSourceQualityContext,
    ResearchSourceQualityJudge,
)


class InlineResearchPolicyProvider(PolicyProvider):
    def load_policy_data(self, policy_name: str) -> dict[str, object]:
        assert policy_name == "research_policy"
        return {
            "version": "test",
            "coverage_gate": {
                "default_required_web_providers": ["tavily", "searxng", "jina_reader"],
                "required_web_provider_counts": {
                    "simple": 2,
                    "comparative": 3,
                    "complex": 3,
                },
                "required_unique_source_counts": {
                    "simple": 5,
                    "comparative": 8,
                    "complex": 12,
                },
            },
            "status_probe": {
                "cache_ttl_seconds": 300.0,
                "provider_order": ["tavily", "searxng", "jina_reader"],
                "search_provider_names": ["tavily", "searxng"],
                "search_probe_query": "web search health check",
                "jina_probe_url": "https://example.com",
            },
            "source_quality": {
                "hard_blocked_domain_suffixes": ["example-social.com"],
                "judge_enabled": True,
                "judge_batch_size": 4,
                "fallback_mode": "keep_on_judge_error",
                "keep_borderline_results": True,
            },
        }


def _citation(
    *,
    title: str,
    origin_url: str,
    source_id: str | None = None,
) -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation(
        source_type=ResearchSourceType.WEB,
        source_provider="tavily",
        retrieval_method="search",
        source_id=source_id or origin_url,
        title=title,
        url=origin_url,
        origin_url=origin_url,
    )


def _paper_citation(
    *,
    title: str,
    source_id: str,
    arxiv_id: str | None = None,
) -> ResearchCanonicalCitation:
    return ResearchCanonicalCitation(
        source_type=ResearchSourceType.PAPER,
        source_provider="arxiv",
        retrieval_method="search",
        source_id=source_id,
        title=title,
        url=f"https://arxiv.org/abs/{arxiv_id or source_id}",
        origin_url=f"https://arxiv.org/abs/{arxiv_id or source_id}",
        arxiv_id=arxiv_id,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id or source_id}.pdf",
    )


def _quality_context() -> ResearchSourceQualityContext:
    plan = ResearchPlanSnapshot(
        research_brief="研究 2025-2026 年 RAG 架构、Agentic RAG、多模态 RAG 和评估基准。",
        complexity=ResearchComplexity.COMPLEX,
        summary="RAG 最近研究",
        subtasks=[
            ResearchPlanSubtask(
                title="Agentic RAG and Multimodal RAG fact collection",
                description="收集与 Agentic RAG、多模态 RAG 直接相关的论文。",
                target_sources=[ResearchSourceTarget.PAPER, ResearchSourceTarget.WEB],
            )
        ],
        target_sources=[ResearchSourceTarget.PAPER, ResearchSourceTarget.WEB],
    )
    return ResearchSourceQualityContext(
        question="当前RAG领域的最近研究",
        plan_snapshot=plan,
    )


class _FakeStructuredJudgeInvoker:
    def __init__(self, *, result: object | None = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.messages: list | None = None

    async def ainvoke(self, messages: list) -> object:
        self.messages = messages
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeStructuredJudgeModel:
    def __init__(self, *, result: object | None = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc
        self.calls: list[tuple[type, str, bool]] = []

    def with_structured_output(
        self,
        schema: type,
        *,
        method: str,
        include_raw: bool,
    ) -> _FakeStructuredJudgeInvoker:
        self.calls.append((schema, method, include_raw))
        return _FakeStructuredJudgeInvoker(result=self._result, exc=self._exc)


def test_final_report_does_not_expose_stale_runtime_todo_statuses() -> None:
    bundle = ResearchSourceBundleBuilder().build(
        target_sources=[ResearchSourceTarget.WEB],
        citations=[
            _citation(
                title="Agentic RAG technical report",
                origin_url="https://example.com/agentic-rag-report",
            )
        ],
        findings=["Agentic RAG 正在从线性检索转向多步规划。"],
    )
    snapshot = ResearchRuntimeContextSnapshot(
        todos_json=[
            {
                "content": "[plan-step-0] Core Literature Collection",
                "status": "in_progress",
            },
            {
                "content": "[plan-step-1] Cross-Validation and Trend Analysis",
                "status": "pending",
            },
        ],
        live_board_json={
            "recent_activity": [
                {
                    "message": "Collecting live RAG evidence",
                    "agent_label": "general-purpose",
                    "status": "in_progress",
                }
            ]
        },
    )

    report = compile_report_from_runtime_context(
        question="当前RAG领域的最近研究",
        source_bundle=bundle,
        runtime_context_snapshot=snapshot,
    )

    assert report is not None
    assert "[in_progress]" not in report.report_md
    assert "[pending]" not in report.report_md
    assert "in_progress" not in report.report_md
    assert "pending" not in report.report_md
    assert "Core Literature Collection" in report.report_md
    assert "Collecting live RAG evidence (general-purpose)" in report.report_md


def test_query_mesh_depth_queries_keep_original_research_topic() -> None:
    plan = ResearchPlanSnapshot(
        research_brief="研究 2025-2026 年 RAG 架构、Agentic RAG、多模态 RAG 和评估基准。",
        complexity=ResearchComplexity.COMPLEX,
        summary="RAG 最近研究",
        subtasks=[
            ResearchPlanSubtask(
                title="Core Literature Collection",
                description="收集核心论文与技术报告。",
                target_sources=[ResearchSourceTarget.PAPER],
            )
        ],
        target_sources=[ResearchSourceTarget.PAPER],
    )

    mesh = build_research_query_mesh(question="当前RAG领域的最近研究", plan_snapshot=plan)

    assert mesh.depth_queries
    assert "RAG" in mesh.depth_queries[0]
    assert "Core Literature Collection" in mesh.depth_queries[0]


def test_source_bundle_builder_does_not_filter_low_trust_social_results() -> None:
    bundle = ResearchSourceBundleBuilder().build(
        target_sources=[ResearchSourceTarget.WEB],
        citations=[
            _citation(
                title="8 RAG architectures for AI Engineers",
                origin_url="https://feeds.example-social.com/p/DVfiS4gD1Gw",
            ),
            _citation(
                title="Agentic RAG technical report",
                origin_url="https://example.com/agentic-rag-report",
            ),
        ],
        findings=["Agentic RAG 正在从线性检索转向多步规划。"],
    )

    assert [citation.origin_url for citation in bundle.citations] == [
        "https://feeds.example-social.com/p/DVfiS4gD1Gw",
        "https://example.com/agentic-rag-report"
    ]


def test_source_bundle_builder_does_not_filter_off_topic_papers() -> None:
    bundle = ResearchSourceBundleBuilder().build(
        target_sources=[ResearchSourceTarget.PAPER],
        citations=[
            _paper_citation(
                title="TokenLight: Controlling Image Generation Attributes with Attribute Tokens",
                source_id="arxiv:2601.00001",
                arxiv_id="2601.00001",
            ),
            _paper_citation(
                title="A Survey on Multimodal Agentic Retrieval-Augmented Generation",
                source_id="arxiv:2604.11419",
                arxiv_id="2604.11419",
            ),
        ],
        findings=["Agentic RAG 与多模态 RAG 正在加速收敛。"],
    )

    assert [citation.title for citation in bundle.citations] == [
        "TokenLight: Controlling Image Generation Attributes with Attribute Tokens",
        "A Survey on Multimodal Agentic Retrieval-Augmented Generation"
    ]


def test_research_policy_loads_model_driven_source_quality_defaults() -> None:
    policy = load_research_policy()

    assert policy.source_quality.hard_blocked_domain_suffixes
    assert policy.source_quality.judge_enabled is True
    assert policy.source_quality.judge_batch_size >= 1
    assert policy.source_quality.fallback_mode == "keep_on_judge_error"
    assert policy.source_quality.keep_borderline_results is True
    assert not hasattr(policy.source_quality, "generic_noise_terms")


def test_research_source_bundle_module_exposes_model_judge() -> None:
    assert hasattr(source_bundle_module, "ResearchSourceQualityJudge")


@pytest.mark.asyncio
async def test_source_quality_judge_applies_hard_blocked_domain_floor() -> None:
    model = _FakeStructuredJudgeModel(
        result={
            "parsed": {
                "decisions": [
                    {
                        "citation_index": 1,
                        "decision": "keep",
                        "relevance_to_question": "high",
                        "support_utility": "direct",
                        "source_trust_signal": "medium",
                        "reason": "主题直接相关",
                    }
                ]
            }
        }
    )
    judge = ResearchSourceQualityJudge(
        model=model,
        policy_provider=InlineResearchPolicyProvider(),
    )

    result = await judge.filter_citations(
        [
            _citation(
                title="8 RAG architectures for AI Engineers",
                origin_url="https://feeds.example-social.com/p/DVfiS4gD1Gw",
            ),
            _citation(
                title="Agentic RAG technical report",
                origin_url="https://example.com/agentic-rag-report",
            ),
        ],
        context=_quality_context(),
    )

    assert [citation.origin_url for citation in result.citations] == [
        "https://example.com/agentic-rag-report"
    ]
    assert result.dropped_count == 1
    assert result.kept_count == 1
    assert result.error_fallback_used is False


@pytest.mark.asyncio
async def test_source_quality_judge_uses_model_to_drop_off_topic_papers() -> None:
    model = _FakeStructuredJudgeModel(
        result={
            "parsed": {
                "decisions": [
                    {
                        "citation_index": 0,
                        "decision": "drop",
                        "relevance_to_question": "low",
                        "support_utility": "none",
                        "source_trust_signal": "medium",
                        "reason": "论文主题离题",
                    },
                    {
                        "citation_index": 1,
                        "decision": "keep",
                        "relevance_to_question": "high",
                        "support_utility": "direct",
                        "source_trust_signal": "high",
                        "reason": "直接覆盖多模态 Agentic RAG",
                    },
                ]
            }
        }
    )
    judge = ResearchSourceQualityJudge(
        model=model,
        policy_provider=InlineResearchPolicyProvider(),
    )

    result = await judge.filter_citations(
        [
            _paper_citation(
                title="TokenLight: Controlling Image Generation Attributes with Attribute Tokens",
                source_id="arxiv:2601.00001",
                arxiv_id="2601.00001",
            ),
            _paper_citation(
                title="A Survey on Multimodal Agentic Retrieval-Augmented Generation",
                source_id="arxiv:2604.11419",
                arxiv_id="2604.11419",
            ),
        ],
        context=_quality_context(),
    )

    assert [citation.title for citation in result.citations] == [
        "A Survey on Multimodal Agentic Retrieval-Augmented Generation"
    ]
    assert result.dropped_count == 1
    assert result.kept_count == 1
    assert result.borderline_count == 0


@pytest.mark.asyncio
async def test_source_quality_judge_keeps_candidates_when_model_errors() -> None:
    judge = ResearchSourceQualityJudge(
        model=_FakeStructuredJudgeModel(exc=RuntimeError("model unavailable")),
        policy_provider=InlineResearchPolicyProvider(),
    )

    result = await judge.filter_citations(
        [
            _paper_citation(
                title="A Survey on Multimodal Agentic Retrieval-Augmented Generation",
                source_id="arxiv:2604.11419",
                arxiv_id="2604.11419",
            )
        ],
        context=_quality_context(),
    )

    assert [citation.title for citation in result.citations] == [
        "A Survey on Multimodal Agentic Retrieval-Augmented Generation"
    ]
    assert result.error_fallback_used is True
    assert result.dropped_count == 0
