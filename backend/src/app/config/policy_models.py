from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResearchComplexityKey = Literal["simple", "comparative", "complex"]
WebSearchProviderId = Literal["tavily", "searxng", "jina_reader"]
_REQUIRED_COMPLEXITY_KEYS = {"simple", "comparative", "complex"}


class SearchQueryRewritePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    freshness_keywords: tuple[str, ...]
    auto_include_domains: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    append_current_year_suffix: bool = True


class SearchFusionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rrf_k: int = Field(ge=1)
    provider_weights: dict[str, float] = Field(default_factory=dict)


class SearchRerankPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_authority_domain_suffixes: tuple[str, ...]
    low_quality_domain_suffixes: tuple[str, ...]
    overlap_bonus_weight: float
    lexical_bonus_per_term: float
    authority_bonus: float
    freshness_bonus: float
    social_penalty: float
    enriched_bonus: float


class SearchQueryPlanningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_clarification_question: str = Field(min_length=1)
    default_ambiguity_true_reason: str = Field(min_length=1)
    default_ambiguity_false_reason: str = Field(min_length=1)
    ambiguity_reason_labels: dict[str, str] = Field(default_factory=dict)
    default_complexity_direct_reason: str = Field(min_length=1)
    default_complexity_multi_query_reason: str = Field(min_length=1)
    default_complexity_decomposition_reason: str = Field(min_length=1)
    guardrail_complexity_direct_reason: str = Field(min_length=1)
    guardrail_complexity_decomposition_reason: str = Field(min_length=1)
    multi_query_label_tokens: tuple[str, ...] = ()
    troubleshoot_keywords: tuple[str, ...] = ()
    coref_markers_zh: tuple[str, ...] = ()
    coref_markers_en: tuple[str, ...] = ()
    compare_keywords: tuple[str, ...] = ()
    multi_target_separators: tuple[str, ...] = ()
    term_alias_keywords: tuple[str, ...] = ()
    taxonomy_query_keywords: tuple[str, ...] = ()
    stable_overview_ask_markers: tuple[str, ...] = ()
    taxonomy_ask_markers: tuple[str, ...] = ()
    taxonomy_drift_keywords: tuple[str, ...] = ()
    stable_overview_keywords: tuple[str, ...] = ()
    multi_entity_signal_keywords: tuple[str, ...] = ()
    question_dimension_keywords: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    decomposition_max_sub_queries: int = Field(ge=1)
    multi_query_fixed_variants: int = Field(ge=1)
    hyde_num_hypotheses: int = Field(ge=1)
    hyde_aggregation: str = Field(min_length=1)
    hyde_regenerate_on_retry: bool = True
    structured_call_max_attempts: int = Field(ge=1)
    structured_call_retryable_reasons: tuple[str, ...] = ()


class SearchEnrichmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low_quality_domain_suffixes: tuple[str, ...]
    snippet_min_length: int = Field(ge=1)
    top_k: int = Field(ge=0)


class SearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    query_rewrite: SearchQueryRewritePolicy
    fusion: SearchFusionPolicy
    rerank: SearchRerankPolicy
    enrichment: SearchEnrichmentPolicy
    query_planning: SearchQueryPlanningPolicy


class ResearchCoverageGatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_required_web_providers: tuple[WebSearchProviderId, ...]
    required_web_provider_counts: dict[ResearchComplexityKey, int]
    required_unique_source_counts: dict[ResearchComplexityKey, int]

    @model_validator(mode="after")
    def _validate_complexity_keys(self) -> "ResearchCoverageGatePolicy":
        provider_count_keys = set(self.required_web_provider_counts.keys())
        unique_source_keys = set(self.required_unique_source_counts.keys())
        if provider_count_keys != _REQUIRED_COMPLEXITY_KEYS:
            raise ValueError("required_web_provider_counts 必须完整定义 simple/comparative/complex")
        if unique_source_keys != _REQUIRED_COMPLEXITY_KEYS:
            raise ValueError(
                "required_unique_source_counts 必须完整定义 simple/comparative/complex"
            )
        return self


class ResearchStatusProbePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_ttl_seconds: float = Field(ge=0.0)
    provider_order: tuple[WebSearchProviderId, ...]
    search_provider_names: tuple[WebSearchProviderId, ...]
    search_probe_query: str = Field(min_length=1)
    jina_probe_url: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_provider_relationships(self) -> "ResearchStatusProbePolicy":
        if not self.provider_order:
            raise ValueError("provider_order 不能为空")
        if not set(self.search_provider_names).issubset(set(self.provider_order)):
            raise ValueError("search_provider_names 必须是 provider_order 的子集")
        return self


class ResearchSourceQualityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_blocked_domain_suffixes: tuple[str, ...] = ()
    judge_enabled: bool = True
    judge_batch_size: int = Field(ge=1)
    fallback_mode: Literal["keep_on_judge_error", "drop_on_judge_error"] = (
        "keep_on_judge_error"
    )
    keep_borderline_results: bool = True


class ResearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    coverage_gate: ResearchCoverageGatePolicy
    status_probe: ResearchStatusProbePolicy
    source_quality: ResearchSourceQualityPolicy
