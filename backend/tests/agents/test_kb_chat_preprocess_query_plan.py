from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic.preprocess import (
    _classify_query_strategy,
    build_prepared_query_bundle,
    generate_variants,
    hyde,
)
from app.core.settings import Settings
from app.services.query_rewrite_service import (
    ComplexityRouteResult,
    QueryListResult,
    QueryRewriteService,
)


@pytest.mark.asyncio
async def test_classify_query_strategy_prefers_original_query_and_bumps_cache_key_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_query = "Chain-of-Thought（CoT，思维链）的主要变体有哪些？"
    captured: dict[str, object] = {}

    async def _fake_classify_complexity(
        self,
        query: str,
        *,
        recall_risk: str | None = None,
        has_multi_target: bool = False,
        is_comparison: bool = False,
    ) -> ComplexityRouteResult:
        captured["query"] = query
        captured["recall_risk"] = recall_risk
        captured["has_multi_target"] = has_multi_target
        captured["is_comparison"] = is_comparison
        return ComplexityRouteResult(
            strategy="multi_query",
            success=True,
            reasoning="术语中存在别名与中英混写，适合多路改写。",
            confidence=0.94,
            risk_flags=["mixed_language", "term_alias"],
            decision_version="kb_chat_complexity_classify_v5",
        )

    monkeypatch.setattr(
        QueryRewriteService,
        "classify_complexity",
        _fake_classify_complexity,
    )

    result = await _classify_query_strategy(
        state={
            "resolved_query": original_query,
            "normalized_query": "Chain-of-Thought main variants",
            "normalized_meta": {
                "recall_risk": "medium",
                "has_multi_target": False,
                "is_comparison": False,
            },
        },
        settings=SimpleNamespace(kb_chat_complexity_cache_enabled=False),
        runtime=None,
    )

    assert captured["query"] == original_query
    assert result["strategy"] == "multi_query"
    assert result["cache_key_version"] == "v2"


@pytest.mark.asyncio
async def test_generate_variants_prefers_original_query_over_normalized_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_query = "Chain-of-Thought（CoT，思维链）的主要变体有哪些？"
    captured: dict[str, object] = {}

    async def _fake_generate_variants(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        captured["query"] = query
        captured["enabled"] = enabled
        return QueryListResult(
            queries=[
                "Chain-of-Thought CoT 思维链 主要变体",
                "CoT 思维链 主要变体 类型 分类",
                "Chain-of-Thought variants Zero-shot CoT Auto-CoT Multimodal CoT",
            ],
            success=True,
            reason="llm_structured",
            latency_ms=7,
        )

    monkeypatch.setattr(
        QueryRewriteService,
        "generate_variants",
        _fake_generate_variants,
    )

    command = await generate_variants(
        {
            "resolved_query": original_query,
            "normalized_query": "Chain-of-Thought variants",
            "stage_summaries": {},
        },
        settings=Settings(),
    )

    assert captured["query"] == original_query
    assert command.goto == "hyde"
    assert command.update["multi_queries"] == [
        "Chain-of-Thought CoT 思维链 主要变体",
        "CoT 思维链 主要变体 类型 分类",
        "Chain-of-Thought variants Zero-shot CoT Auto-CoT Multimodal CoT",
    ]


def test_build_prepared_query_bundle_skips_hyde_for_direct_stable_overview_query() -> None:
    bundle = build_prepared_query_bundle(
        original_query="AI Agent 的六大核心组件是什么？",
        normalized_query="AI Agent 的六大核心组件是什么？",
        strategy="direct",
        sub_queries=[],
        sub_query_specs=[],
        multi_queries=[],
        hyde_docs=[
            "执行层负责将认知层的指令转化为具体的系统调用、机器人动作或业务流程，并通过监控与回馈机制实时校验执行结果。"
        ],
        normalized_meta={"recall_risk": "medium"},
        budget={
            "max_candidates": 4,
            "min_queries": 2,
            "quality_threshold": 0.0,
            "include_main": True,
        },
    )

    query_items = bundle["query_items"]
    assert [item["kind"] for item in query_items] == ["main"]
    assert bundle["query_bundle"]["kind_breakdown"] == {"main": 1}
    assert any(
        isinstance(item, dict)
        and item.get("kind") == "hyde"
        and item.get("reason") == "stable_overview_direct_disable_hyde"
        for item in bundle["message_plan"]["dropped"]
    )


@pytest.mark.asyncio
async def test_hyde_skips_direct_stable_overview_query_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {"call_count": 0}

    async def _fake_hyde(
        self,
        query: str,
        *,
        enabled: bool | None = None,
    ) -> QueryListResult:
        captured["call_count"] += 1
        return QueryListResult(
            queries=["不应执行到这里"],
            success=True,
            reason="llm_structured",
            latency_ms=5,
        )

    monkeypatch.setattr(QueryRewriteService, "hyde", _fake_hyde)

    result = await hyde(
        {
            "user_input": "AI Agent 的六大核心组件是什么？",
            "resolved_query": "AI Agent 的六大核心组件是什么？",
            "normalized_query": "AI Agent 的六大核心组件是什么？",
            "query_strategy": "direct",
            "stage_summaries": {},
        },
        settings=Settings(),
    )

    assert captured["call_count"] == 0
    assert result["hyde_docs"] == []
    assert result["stage_summaries"]["hyde"]["driver"] == "rule"
    assert result["stage_summaries"]["hyde"]["success"] is True
    assert result["stage_summaries"]["hyde"]["reason"] == "stable_overview_direct_skip_hyde"
    assert result["stage_summaries"]["hyde"]["requested_count"] == 0
    assert result["stage_summaries"]["hyde"]["generated_count"] == 0
