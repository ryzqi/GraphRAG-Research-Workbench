import types

import pytest

from app.agents.kb_chat_agentic.schemas import AmbiguityDecision, ClarificationSlotDecision
from app.agents.kb_chat_agentic.schemas import ComplexityDecision
from app.agents.kb_chat_agentic.schemas import NormalizeDecision
from app.services.query_rewrite_service import QueryRewriteService
from app.services.query_rewrite_service import StructuredCallResult


@pytest.fixture
def settings():
    return types.SimpleNamespace(
        retrieval_query_rewrite_timeout_seconds=15,
        retrieval_query_rewrite_max_tokens=64,
        kb_chat_ambiguity_check_enabled=True,
        kb_chat_normalize_llm_enabled=True,
        kb_chat_normalize_alias_max=4,
        kb_chat_normalize_timeout_seconds=0.8,
        kb_chat_hyde_enabled=False,
    )


@pytest.mark.asyncio
async def test_coref_rewrite_resolves_recent_turn_reference(settings):
    svc = QueryRewriteService(settings=settings)

    result = await svc.coref_rewrite(
        "这个流程怎么配置？",
        recent_turns=[
            {"role": "user", "text": "请介绍 OAuth 登录流程"},
            {"role": "assistant", "text": "可以从回调地址和授权范围开始配置"},
        ],
        summary_text="",
        memory_snippet="",
    )

    assert result.rewritten is True
    assert "OAuth 登录流程" in result.query
    assert isinstance(result.meta, dict)
    assert float(result.meta.get("confidence", 0.0)) >= 0.72
    assert result.meta.get("needs_clarification") is False


@pytest.mark.asyncio
async def test_coref_rewrite_keeps_query_when_low_confidence(settings):
    svc = QueryRewriteService(settings=settings)

    result = await svc.coref_rewrite(
        "这个怎么样",
        recent_turns=[],
        summary_text="",
        memory_snippet="",
    )

    assert result.query == "这个怎么样"
    assert result.rewritten is False
    assert isinstance(result.meta, dict)
    assert result.meta.get("needs_clarification") is True
    assert result.reason in {"no_candidate", "low_confidence", "unchanged_after_apply"}


@pytest.mark.asyncio
async def test_ambiguity_check_returns_structured_payload(monkeypatch, settings):
    svc = QueryRewriteService(settings=settings)

    async def _fake_structured(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        payload = AmbiguityDecision(
            ambiguous=True,
            reason_code="missing_entity",
            confidence=0.86,
            reasoning="missing target entity",
            clarifying_question="请问你指的是哪个具体方案？",
            missing_slots=[
                ClarificationSlotDecision(
                    key="entity",
                    label="对象",
                    required=True,
                    options=["方案A", "方案B"],
                )
            ],
            suggested_answers=["方案A", "方案B"],
        )
        return StructuredCallResult(payload=payload, success=True, reason="model_ok", latency_ms=9)

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)

    result = await svc.ambiguity_check("这个方案怎么做", timeout_seconds=0.5, coref_meta=None)

    assert result.ambiguous is True
    assert result.reason == "model_ok"
    assert result.reason_code == "missing_entity"
    assert result.confidence == pytest.approx(0.86)
    assert result.fallback_used is False
    assert isinstance(result.clarification_payload, dict)
    assert result.clarification_payload["reason_code"] == "missing_entity"
    assert result.clarification_payload["slots"][0]["key"] == "entity"


@pytest.mark.asyncio
async def test_ambiguity_check_guardrail_fallback_when_model_fails(monkeypatch, settings):
    svc = QueryRewriteService(settings=settings)

    async def _fake_structured(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return StructuredCallResult(payload=None, success=False, reason="timeout", latency_ms=11)

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)

    result = await svc.ambiguity_check(
        "这个怎么做",
        timeout_seconds=0.5,
        coref_meta={"needs_clarification": True},
    )

    assert result.ambiguous is True
    assert result.fallback_used is True
    assert result.reason == "timeout"
    assert result.reason_code == "coref_uncertain"
    assert isinstance(result.clarification_payload, dict)


@pytest.mark.asyncio
async def test_normalize_rewrite_prefers_structured_output_when_constraints_preserved(monkeypatch, settings):
    svc = QueryRewriteService(settings=settings)

    async def _fake_structured(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        payload = NormalizeDecision(
            canonical_query="2024 platform availability SLA",
            aliases=["platform SLA 2024", "availability target"],
            entities=["platform"],
            time_constraints=["2024"],
            metric_constraints=["availability", "SLA"],
            scope_constraints=[],
            recall_risk="medium",
            drift_risk=False,
            reasoning="keep time and metric constraints",
        )
        return StructuredCallResult(payload=payload, success=True, reason="model_ok", latency_ms=7)

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)

    result = await svc.normalize_rewrite("2024 platform availability")

    assert result.query == "2024 platform availability SLA"
    assert result.reason == "llm_structured"
    assert result.meta["source"] == "llm_structured"
    assert result.meta["constraint_preserved"] is True


@pytest.mark.asyncio
async def test_normalize_rewrite_falls_back_when_structured_query_drops_numeric_constraint(monkeypatch, settings):
    svc = QueryRewriteService(settings=settings)

    async def _fake_structured(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        payload = NormalizeDecision(
            canonical_query="platform availability",
            aliases=["service uptime"],
            entities=["platform"],
            time_constraints=[],
            metric_constraints=["availability"],
            scope_constraints=[],
            recall_risk="medium",
            drift_risk=False,
            reasoning="incorrectly dropped year",
        )
        return StructuredCallResult(payload=payload, success=True, reason="model_ok", latency_ms=7)

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)

    result = await svc.normalize_rewrite("2024 platform availability")

    assert result.query == "2024 platform availability"
    assert result.reason == "rule_fallback"
    assert result.meta["source"] == "rule_fallback"
    assert result.meta["fallback_reason"] == "constraint_not_preserved"


@pytest.mark.asyncio
async def test_classify_complexity_returns_confidence_and_signals(monkeypatch, settings):
    svc = QueryRewriteService(settings=settings)

    async def _fake_structured(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        payload = ComplexityDecision(
            reasoning="比较问题且多目标，需拆分汇总",
            strategy="decomposition",
            confidence=0.91,
            risk_flags=["comparison", "multi_target", "constraint_heavy"],
            decision_version="kb_chat_complexity_router_v4",
        )
        return StructuredCallResult(
            payload=payload,
            success=True,
            reason="model_ok",
            latency_ms=10,
        )

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)

    result = await svc.classify_complexity(
        "A和B优缺点分别是什么",
        recall_risk="medium",
        has_multi_target=True,
        is_comparison=True,
        timeout_seconds=1.0,
    )

    assert result.success is True
    assert result.strategy == "decomposition"
    assert result.confidence == pytest.approx(0.91)
    assert result.risk_flags == ["comparison", "multi_target", "constraint_heavy"]
    assert result.decision_version == "kb_chat_complexity_router_v4"


@pytest.mark.asyncio
async def test_classify_complexity_falls_back_to_direct_when_model_fails(monkeypatch, settings):
    svc = QueryRewriteService(settings=settings)

    async def _fake_structured(*args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return StructuredCallResult(
            payload=None, success=False, reason="timeout", latency_ms=12
        )

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)

    result = await svc.classify_complexity("SLA 是什么", timeout_seconds=1.0)

    assert result.success is False
    assert result.strategy == "direct"
    assert result.confidence == 0.0
    assert result.risk_flags == ["llm_failed_fallback_direct"]
    assert result.decision_version == "kb_chat_complexity_router_v4"
