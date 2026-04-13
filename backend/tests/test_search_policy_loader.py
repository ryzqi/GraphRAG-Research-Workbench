from __future__ import annotations

from pathlib import Path

import pytest

from app.config.policy_loader import (
    load_frontend_runtime_policy,
    load_search_policy,
)
from app.config.policy_provider import StaticFilePolicyProvider


def _policy_base_path() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "app" / "config" / "policies"


def test_search_policy_loader_reads_versioned_yaml() -> None:
    provider = StaticFilePolicyProvider(base_path=_policy_base_path())

    policy = load_search_policy(provider=provider)

    assert "最新" in policy.query_rewrite.freshness_keywords
    assert policy.query_rewrite.auto_include_domains["langchain"] == (
        "docs.langchain.com",
    )
    assert policy.query_rewrite.append_current_year_suffix is True
    assert policy.fusion.rrf_k == 60
    assert policy.fusion.provider_weights["searxng"] == pytest.approx(0.85)
    assert "docs.langchain.com" in policy.rerank.high_authority_domain_suffixes
    assert policy.rerank.social_penalty == pytest.approx(0.35)
    assert policy.enrichment.snippet_min_length == 180
    assert policy.enrichment.top_k == 2
    assert (
        policy.query_planning.default_clarification_question
        == "为了更准确地回答，请补充你指的是哪个对象、范围或时间？"
    )
    assert (
        policy.query_planning.ambiguity_reason_labels["missing_entity"]
        == "缺少具体对象"
    )
    assert "报错" in policy.query_planning.troubleshoot_keywords
    assert "术语化查询" in policy.query_planning.multi_query_label_tokens
    assert "this" in policy.query_planning.coref_markers_en
    assert "比较" in policy.query_planning.compare_keywords
    assert "分别" in policy.query_planning.multi_entity_signal_keywords
    assert (
        policy.query_planning.question_dimension_keywords["技术架构"][0]
        == "技术架构"
    )
    assert policy.query_planning.decomposition_max_sub_queries == 5
    assert policy.query_planning.multi_query_fixed_variants == 3
    assert policy.query_planning.hyde_num_hypotheses == 5
    assert policy.query_planning.hyde_aggregation == "mean_embedding"
    assert policy.query_planning.hyde_regenerate_on_retry is True
    assert policy.query_planning.structured_call_max_attempts == 2
    assert (
        "invalid_schema"
        in policy.query_planning.structured_call_retryable_reasons
    )


def test_frontend_runtime_policy_loader_reads_versioned_yaml() -> None:
    provider = StaticFilePolicyProvider(base_path=_policy_base_path())

    policy = load_frontend_runtime_policy(provider=provider)

    assert policy.status_polling_interval_ms == 2000
    assert policy.ingestion_stream_fallback_polling_steps_ms == [1000, 2000, 5000]
    assert policy.ingestion_stream_retry_multiplier == 2
    assert policy.server_prefetch_cache_revalidate_seconds == 30
    assert policy.download_allowed_hosts == []
