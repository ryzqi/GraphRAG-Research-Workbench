from __future__ import annotations

import app.agents.kb_chat_agentic.reflection as reflection
import app.agents.kb_chat_trace_display_shared as trace_display
import app.services.query_rewrite_items as query_rewrite_items
import app.services.query_rewrite_service as query_rewrite_service
import app.services.query_rewrite_text as query_rewrite_text
from app.config.policy_models import SearchPolicy
from app.services.query_rewrite_contracts import StructuredCallResult
from pydantic import BaseModel


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
                "rrf_k": 60,
                "provider_weights": {
                    "tavily": 1.0,
                },
            },
            "rerank": {
                "high_authority_domain_suffixes": ["docs.langchain.com"],
                "low_quality_domain_suffixes": ["noise.example"],
                "overlap_bonus_weight": 0.9,
                "lexical_bonus_per_term": 0.08,
                "authority_bonus": 0.45,
                "freshness_bonus": 0.12,
                "social_penalty": 0.35,
                "enriched_bonus": 0.15,
            },
            "enrichment": {
                "low_quality_domain_suffixes": ["noise.example"],
                "snippet_min_length": 180,
                "top_k": 2,
            },
            "query_planning": {
                "default_clarification_question": "请明确你想指的是哪个系统对象？",
                "default_ambiguity_true_reason": "缺少关键上下文，必须先澄清。",
                "default_ambiguity_false_reason": "上下文足够，可以继续。",
                "ambiguity_reason_labels": {
                    "missing_entity": "对象不明确",
                    "missing_scope": "范围不明确",
                    "missing_time": "时间不明确",
                    "missing_metric": "指标不明确",
                    "coref_uncertain": "指代不明确",
                    "mixed": "信息不完整",
                },
                "default_complexity_direct_reason": "默认走 direct。",
                "default_complexity_multi_query_reason": "默认走 multi-query。",
                "default_complexity_decomposition_reason": "默认走 decomposition。",
                "guardrail_complexity_direct_reason": "guardrail 改判 direct。",
                "guardrail_complexity_decomposition_reason": "guardrail 改判 decomposition。",
                "multi_query_label_tokens": ["AlphaTag", "BetaTag"],
                "troubleshoot_keywords": ["paniccode", "tracefix"],
                "coref_markers_zh": ["该对象"],
                "coref_markers_en": ["referback"],
                "compare_keywords": ["duelmode"],
                "multi_target_separators": [" plus "],
                "term_alias_keywords": ["别称"],
                "taxonomy_query_keywords": ["关键层级"],
                "stable_overview_ask_markers": ["是什么"],
                "taxonomy_ask_markers": ["是什么"],
                "taxonomy_drift_keywords": ["性能"],
                "stable_overview_keywords": ["关键层级"],
                "multi_entity_signal_keywords": ["逐条覆盖"],
                "question_dimension_keywords": {
                    "成本": ["成本构成"],
                    "流程": ["流程"],
                },
                "decomposition_max_sub_queries": 2,
                "multi_query_fixed_variants": 2,
                "hyde_num_hypotheses": 2,
                "hyde_aggregation": "weighted_mean",
                "hyde_regenerate_on_retry": False,
                "structured_call_max_attempts": 3,
                "structured_call_retryable_reasons": [
                    "temporary_retry",
                    "invalid_schema",
                ],
            },
        }
    )


def test_query_rewrite_text_uses_policy_for_reason_text(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )

    assert query_rewrite_text._default_clarification_question() == (
        "请明确你想指的是哪个系统对象？"
    )
    assert query_rewrite_text._default_ambiguity_reason(ambiguous=True) == (
        "缺少关键上下文，必须先澄清。"
    )
    assert query_rewrite_text._resolve_ambiguity_reason_label("missing_entity") == (
        "对象不明确"
    )
    assert query_rewrite_text._default_complexity_reason("multi_query") == (
        "默认走 multi-query。"
    )
    assert query_rewrite_text._guardrail_complexity_reason("decomposition") == (
        "guardrail 改判 decomposition。"
    )


def test_query_rewrite_items_use_policy_tokens_and_troubleshoot_keywords(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )

    candidates = query_rewrite_items._rule_based_multi_query_candidates("paniccode")
    assert candidates[1] == "paniccode 原因 排查"
    assert candidates[2] == "paniccode 解决方案 最佳实践"
    assert query_rewrite_items._is_label_stuffed_multi_query(
        "原问题 AlphaTag",
        original_query="原问题",
    )


def test_query_rewrite_text_uses_policy_keyword_heuristics(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )

    assert query_rewrite_text._contains_coref_marker("请结合 referback 继续回答")
    assert query_rewrite_text._looks_compare_or_multi_target("Foo duelmode Bar")
    assert query_rewrite_text._looks_stable_overview_query("Foo 关键层级是什么")


def test_query_rewrite_items_use_policy_execution_budgets(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )

    variants, fallback_used, invalid_reason = (
        query_rewrite_items._coerce_fixed_multi_query_variants(
            ["原问题", "变体一", "变体二", "变体三"],
            original_query="原问题",
        )
    )
    hyde_docs = query_rewrite_items._normalize_hyde_documents(["A", "B", "C"])

    assert variants == ["原问题", "变体一"]
    assert fallback_used is False
    assert invalid_reason is None
    assert hyde_docs == ["A", "B"]


def test_reflection_shares_policy_driven_multi_entity_heuristics(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )

    hint = reflection._build_answer_coverage_hint("Foo 和 Bar 逐条覆盖成本构成")

    assert "Foo" in hint
    assert "Bar" in hint
    assert "成本" in hint


class _DummyStructuredPayload(BaseModel):
    value: str


def test_query_rewrite_service_uses_policy_structured_retry_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )
    service = query_rewrite_service.QueryRewriteService()
    monkeypatch.setattr(
        service._prompts,
        "render_with_few_shot",
        lambda prompt_key, **kwargs: "rendered prompt",
    )
    call_count = {"value": 0}

    async def _fake_invoke_model_structured(**_: object) -> StructuredCallResult:
        call_count["value"] += 1
        if call_count["value"] < 3:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason="temporary_retry",
                latency_ms=0,
            )
        return StructuredCallResult(
            payload=_DummyStructuredPayload(value="ok"),
            success=True,
            reason=None,
            latency_ms=0,
        )

    monkeypatch.setattr(service, "_invoke_model_structured", _fake_invoke_model_structured)

    result = query_rewrite_service.asyncio.run(
        service._call_prompt_structured(
            "kb_chat/normalize_query",
            schema=_DummyStructuredPayload,
            max_tokens=32,
            question="原问题",
        )
    )

    assert result.success is True
    assert isinstance(result.payload, _DummyStructuredPayload)
    assert call_count["value"] == 3


def test_query_rewrite_service_and_trace_display_share_policy_reason_text(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        query_rewrite_text,
        "load_search_policy",
        lambda: _build_search_policy(),
    )

    assert query_rewrite_service.QueryRewriteService._resolve_ambiguity_business_reason(
        ambiguous=True,
        model_reason=None,
        reason_code="missing_entity",
    ) == "对象不明确"
    assert query_rewrite_service.QueryRewriteService._fallback_complexity_route(
        query="普通问题",
        recall_risk=None,
        has_multi_target=False,
        is_comparison=False,
        failure_reason=None,
        latency_ms=0,
    ).reasoning == "默认走 direct。"
    assert trace_display._resolve_ambiguity_reason(
        summary={"ambiguous": True, "reason_code": "missing_entity"},
        reflection={},
        default_reason="fallback",
    ) == "对象不明确"
