from __future__ import annotations

import app.search.web.query_rewrite as query_rewrite
from app.config.policy_models import SearchPolicy


def _build_search_policy(*, append_current_year_suffix: bool) -> SearchPolicy:
    return SearchPolicy.model_validate(
        {
            "version": "test",
            "query_rewrite": {
                "freshness_keywords": ["latest", "release"],
                "auto_include_domains": {
                    "langchain": ["docs.langchain.com"],
                },
                "append_current_year_suffix": append_current_year_suffix,
            },
            "fusion": {
                "rrf_k": 60,
                "provider_weights": {
                    "tavily": 1.0,
                    "searxng": 0.85,
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
                "multi_query_label_tokens": ["标签"],
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


def test_query_rewrite_uses_runtime_year_and_policy_domains(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        query_rewrite,
        "load_search_policy",
        lambda: _build_search_policy(append_current_year_suffix=True),
        raising=False,
    )
    monkeypatch.setattr(query_rewrite, "_current_year", lambda: 2031, raising=False)

    plan = query_rewrite.build_search_query_plan("latest langchain release")

    assert "site:docs.langchain.com latest langchain release" in plan.rewritten_queries
    assert "latest langchain release 2031" in plan.rewritten_queries
    assert all("2026" not in item for item in plan.rewritten_queries)


def test_query_rewrite_policy_can_disable_year_suffix(monkeypatch) -> None:
    monkeypatch.setattr(
        query_rewrite,
        "load_search_policy",
        lambda: _build_search_policy(append_current_year_suffix=False),
        raising=False,
    )
    monkeypatch.setattr(query_rewrite, "_current_year", lambda: 2031, raising=False)

    plan = query_rewrite.build_search_query_plan("latest langchain release")

    assert "latest langchain release 2031" not in plan.rewritten_queries
    assert all("2026" not in item for item in plan.rewritten_queries)
