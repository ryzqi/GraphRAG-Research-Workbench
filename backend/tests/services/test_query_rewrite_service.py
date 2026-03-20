from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.query_rewrite_service as query_rewrite_service_module
from app.agents.kb_chat_agentic.schemas import AmbiguityDecision, ComplexityDecision
from app.services.query_rewrite_service import (
    QueryRewriteService,
    _entity_seed_queries,
    _rule_normalize_query,
    build_query_items,
)


def test_build_query_items_drops_invisible_only_candidates() -> None:
    items = build_query_items(
        main_query="main query",
        sub_queries=["\u200e", "sub query"],
        variants=["\u2066", "variant query"],
        hyde_docs=["\u00ad", "hyde query"],
    )

    assert items == [
        {
            "kind": "main",
            "query": "main query",
            "use_dense": True,
            "use_bm25": True,
        },
        {
            "kind": "subquery",
            "query": "sub query",
            "index": 1,
            "origin": "decomposition",
            "subquery_id": "sq_2",
            "priority": 2,
            "coverage_tags": [],
            "purpose": "",
            "use_dense": True,
            "use_bm25": True,
        },
        {
            "kind": "variant",
            "query": "variant query",
            "index": 1,
            "use_dense": True,
            "use_bm25": True,
        },
        {
            "kind": "hyde",
            "query": "hyde query",
            "index": 0,
            "use_dense": True,
            "use_bm25": False,
            "hyde_queries": ["hyde query"],
            "hyde_aggregation": "mean_embedding",
        },
    ]


def test_rule_normalize_query_does_not_promote_focus_terms_to_aliases() -> None:
    query, meta = _rule_normalize_query("介绍一下react框架", alias_limit=4)

    assert query == "介绍一下react框架"
    assert meta["entities"] == ["react", "介绍一下", "框架"]
    assert meta["aliases"] == []


def test_entity_seed_queries_do_not_append_aliases_or_entities() -> None:
    seed = _entity_seed_queries(
        normalized_query="介绍一下react框架",
        queries=["react 框架"],
        aliases=["react"],
        entities=["react", "框架"],
        max_candidates=8,
    )

    assert seed == ["介绍一下react框架", "react 框架"]


@pytest.mark.asyncio
async def test_ambiguity_check_uses_model_with_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class _FakeStructuredRunnable:
        async def ainvoke(self, messages: object) -> dict[str, object]:
            calls["invoke_messages"] = messages
            return {
                "raw": object(),
                "parsed": AmbiguityDecision(
                    ambiguous=False,
                    reason_code="missing_metric",
                    confidence=0.91,
                    reasoning="现有问题已足够明确，可直接检索。",
                    clarifying_question="",
                    missing_slots=[],
                    suggested_answers=[],
                ),
                "parsing_error": None,
            }

    class _FakeModel:
        def bind(self, **kwargs: object) -> "_FakeModel":
            calls["bind_kwargs"] = kwargs
            return self

        def with_structured_output(
            self, schema: type[AmbiguityDecision], *, include_raw: bool = False
        ) -> _FakeStructuredRunnable:
            calls["schema"] = schema
            calls["include_raw"] = include_raw
            return _FakeStructuredRunnable()

    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_chat_model",
        lambda **_: _FakeModel(),
    )
    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ambiguity_check should not use create_agent")
        ),
    )

    service = QueryRewriteService(settings=SimpleNamespace())
    service._prompts = SimpleNamespace(
        render_with_few_shot=lambda *args, **kwargs: "歧义判断测试 prompt"
    )

    result = await service.ambiguity_check("2024 年平台可用性是多少？")

    assert calls["bind_kwargs"] == {"max_tokens": 320}
    assert calls["schema"] is AmbiguityDecision
    assert calls["include_raw"] is True
    assert result.ambiguous is False
    assert result.reason == "现有问题已足够明确，可直接检索。"
    assert result.failure_reason is None
    assert result.model_reason == "现有问题已足够明确，可直接检索。"


@pytest.mark.asyncio
async def test_ambiguity_check_fail_open_keeps_business_reason_when_parse_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStructuredRunnable:
        async def ainvoke(self, messages: object) -> dict[str, object]:
            _ = messages
            return {
                "raw": object(),
                "parsed": None,
                "parsing_error": ValueError("bad structured output"),
            }

    class _FakeModel:
        def bind(self, **kwargs: object) -> "_FakeModel":
            _ = kwargs
            return self

        def with_structured_output(
            self, schema: type[AmbiguityDecision], *, include_raw: bool = False
        ) -> _FakeStructuredRunnable:
            _ = schema, include_raw
            return _FakeStructuredRunnable()

    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_chat_model",
        lambda **_: _FakeModel(),
    )
    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ambiguity_check should not use create_agent")
        ),
    )

    service = QueryRewriteService(settings=SimpleNamespace())
    service._prompts = SimpleNamespace(
        render_with_few_shot=lambda *args, **kwargs: "歧义判断测试 prompt"
    )

    result = await service.ambiguity_check("2024 年平台可用性是多少？")

    assert result.ambiguous is False
    assert result.reason == "未命中需澄清信号，可直接继续检索。"
    assert result.failure_reason == "error"
    assert result.fallback_used is True
    assert result.model_reason == "未命中需澄清信号，可直接继续检索。"


@pytest.mark.asyncio
async def test_classify_complexity_uses_model_with_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class _FakeStructuredRunnable:
        async def ainvoke(self, messages: object) -> dict[str, object]:
            calls["invoke_messages"] = messages
            return {
                "raw": object(),
                "parsed": ComplexityDecision(
                    reasoning="这是明确的比较型多目标问题，需要拆成独立检索视角后再汇总。",
                    strategy="decomposition",
                    confidence=0.97,
                    risk_flags=["comparison", "multi_target"],
                    decision_version="kb_chat_complexity_classify_v5",
                ),
                "parsing_error": None,
            }

    class _FakeModel:
        def bind(self, **kwargs: object) -> "_FakeModel":
            calls["bind_kwargs"] = kwargs
            return self

        def with_structured_output(
            self, schema: type[ComplexityDecision], *, include_raw: bool = False
        ) -> _FakeStructuredRunnable:
            calls["schema"] = schema
            calls["include_raw"] = include_raw
            return _FakeStructuredRunnable()

    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_chat_model",
        lambda **_: _FakeModel(),
    )
    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("classify_complexity should not use create_agent")
        ),
    )

    service = QueryRewriteService(settings=SimpleNamespace())
    service._prompts = SimpleNamespace(
        render_with_few_shot=lambda *args, **kwargs: "复杂度分类测试 prompt"
    )

    result = await service.classify_complexity(
        "比较 ReAct 和 Plan-and-Solve 框架",
        recall_risk="medium",
        has_multi_target=True,
        is_comparison=True,
    )

    assert calls["bind_kwargs"] == {"max_tokens": 256}
    assert calls["schema"] is ComplexityDecision
    assert calls["include_raw"] is True
    assert result.strategy == "decomposition"
    assert result.success is True
    assert result.reasoning == "这是明确的比较型多目标问题，需要拆成独立检索视角后再汇总。"
    assert result.failure_reason is None


@pytest.mark.asyncio
async def test_classify_complexity_fail_open_keeps_decomposition_for_comparison_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStructuredRunnable:
        async def ainvoke(self, messages: object) -> dict[str, object]:
            _ = messages
            return {
                "raw": object(),
                "parsed": None,
                "parsing_error": ValueError("bad structured output"),
            }

    class _FakeModel:
        def bind(self, **kwargs: object) -> "_FakeModel":
            _ = kwargs
            return self

        def with_structured_output(
            self, schema: type[ComplexityDecision], *, include_raw: bool = False
        ) -> _FakeStructuredRunnable:
            _ = schema, include_raw
            return _FakeStructuredRunnable()

    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_chat_model",
        lambda **_: _FakeModel(),
    )
    monkeypatch.setattr(
        query_rewrite_service_module,
        "create_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("classify_complexity should not use create_agent")
        ),
    )

    service = QueryRewriteService(settings=SimpleNamespace())
    service._prompts = SimpleNamespace(
        render_with_few_shot=lambda *args, **kwargs: "复杂度分类测试 prompt"
    )

    result = await service.classify_complexity(
        "比较 ReAct 和 Plan-and-Solve 框架",
        recall_risk="medium",
        has_multi_target=True,
        is_comparison=True,
    )

    assert result.strategy == "decomposition"
    assert result.success is False
    assert result.reasoning == "命中比较或多目标信号，按问题拆解处理。"
    assert result.failure_reason == "error"
