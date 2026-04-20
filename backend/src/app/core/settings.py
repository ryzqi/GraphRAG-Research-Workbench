from __future__ import annotations

from functools import lru_cache
import sys
from typing import Any

from pydantic import Field, field_validator

from app.config.deploy_settings import DeploySettings
from app.config.validators import (
    DEFAULT_INGESTION_BLOCKED_CIDRS_V4,
    DEFAULT_INGESTION_BLOCKED_CIDRS_V6,
    DEFAULT_INGESTION_METADATA_BLOCKLIST,
    parse_string_list,
    prefer_ipv4_loopback_url,
    validate_startup_settings,
)

__all__ = ["Settings", "get_settings", "validate_startup_settings"]


class Settings(DeploySettings):
    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

    milvus_host: str = Field("localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(19530, alias="MILVUS_PORT")
    milvus_collection: str = Field("kb_chunks_v1", alias="MILVUS_COLLECTION")
    milvus_text_analyzer: str = Field("chinese", alias="MILVUS_TEXT_ANALYZER")
    milvus_text_analyzer_filters: list[str] = Field(
        default_factory=list, alias="MILVUS_TEXT_ANALYZER_FILTERS"
    )

    llm_timeout_seconds: float = Field(30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_input_tokens: int | None = Field(80_000, alias="LLM_MAX_INPUT_TOKENS")
    llm_output_version: str = Field("responses/v1", alias="LLM_OUTPUT_VERSION")
    general_chat_replay_mode: str = Field("auto", alias="GENERAL_CHAT_REPLAY_MODE")
    interactive_run_stale_timeout_seconds: int = Field(
        300, ge=1, alias="INTERACTIVE_RUN_STALE_TIMEOUT_SECONDS"
    )

    embedding_retry_max_retries: int = Field(
        2, ge=0, alias="EMBEDDING_RETRY_MAX_RETRIES"
    )
    embedding_retry_base_delay_seconds: float = Field(
        0.2, ge=0.0, alias="EMBEDDING_RETRY_BASE_DELAY_SECONDS"
    )
    embedding_retry_jitter_ratio: float = Field(
        0.2, ge=0.0, alias="EMBEDDING_RETRY_JITTER_RATIO"
    )
    embedding_breaker_failure_threshold: int = Field(
        3, ge=1, alias="EMBEDDING_BREAKER_FAILURE_THRESHOLD"
    )
    embedding_breaker_open_seconds: float = Field(
        30.0, ge=0.0, alias="EMBEDDING_BREAKER_OPEN_SECONDS"
    )

    mcp_enabled: bool = Field(False, alias="MCP_ENABLED")
    mcp_http_timeout_seconds: int = Field(30, alias="MCP_HTTP_TIMEOUT_SECONDS")
    mcp_stdio_timeout_seconds: int = Field(10, alias="MCP_STDIO_TIMEOUT_SECONDS")
    mcp_parallel_load_enabled: bool = Field(
        True, alias="MCP_PARALLEL_LOAD_ENABLED"
    )

    memory_enabled: bool = Field(False, alias="MEMORY_ENABLED")
    memory_store_backend: str = Field("postgres", alias="MEMORY_STORE_BACKEND")
    memory_store_url: str | None = Field(None, alias="MEMORY_STORE_URL")
    memory_store_path: str = Field("/memories/", alias="MEMORY_STORE_PATH")

    web_search_api_key: str | None = Field(None, alias="WEB_SEARCH_API_KEY")
    web_search_cache_enabled: bool = Field(True, alias="WEB_SEARCH_CACHE_ENABLED")
    web_search_cache_ttl_seconds: int = Field(300, alias="WEB_SEARCH_CACHE_TTL_SECONDS")
    web_search_retry_max: int = Field(2, alias="WEB_SEARCH_RETRY_MAX")
    web_search_retry_backoff_seconds: float = Field(
        1.5, alias="WEB_SEARCH_RETRY_BACKOFF_SECONDS"
    )
    web_search_rate_limit_per_minute: int = Field(
        0, alias="WEB_SEARCH_RATE_LIMIT_PER_MINUTE"
    )
    web_search_max_concurrency: int = Field(5, alias="WEB_SEARCH_MAX_CONCURRENCY")
    web_search_default_search_depth: str = Field(
        "basic", alias="WEB_SEARCH_DEFAULT_SEARCH_DEPTH"
    )
    web_search_default_time_range: str = Field(
        "month", alias="WEB_SEARCH_DEFAULT_TIME_RANGE"
    )
    web_search_default_max_results: int = Field(
        5, alias="WEB_SEARCH_DEFAULT_MAX_RESULTS"
    )
    web_search_auto_parameters: bool = Field(True, alias="WEB_SEARCH_AUTO_PARAMETERS")
    web_search_include_usage: bool = Field(False, alias="WEB_SEARCH_INCLUDE_USAGE")
    jina_read_enabled: bool = Field(True, alias="JINA_READ_ENABLED")
    jina_read_base_url: str = Field("https://r.jina.ai", alias="JINA_READ_BASE_URL")
    web_extract_default_depth: str = Field("basic", alias="WEB_EXTRACT_DEFAULT_DEPTH")
    web_crawl_default_depth: str = Field("basic", alias="WEB_CRAWL_DEFAULT_DEPTH")
    web_crawl_default_limit: int = Field(10, alias="WEB_CRAWL_DEFAULT_LIMIT")
    web_crawl_default_max_depth: int = Field(3, alias="WEB_CRAWL_DEFAULT_MAX_DEPTH")
    web_crawl_default_max_breadth: int = Field(
        20, alias="WEB_CRAWL_DEFAULT_MAX_BREADTH"
    )
    web_research_output_format: str = Field(
        "report", alias="WEB_RESEARCH_OUTPUT_FORMAT"
    )
    web_research_citation_format: str = Field(
        "numbered", alias="WEB_RESEARCH_CITATION_FORMAT"
    )
    web_research_output_schema: str | None = Field(
        None, alias="WEB_RESEARCH_OUTPUT_SCHEMA"
    )
    web_research_model: str | None = Field(None, alias="WEB_RESEARCH_MODEL")
    web_research_poll_interval_seconds: float = Field(
        2.0, alias="WEB_RESEARCH_POLL_INTERVAL_SECONDS"
    )

    retrieval_default_top_k: int = Field(12, alias="RETRIEVAL_DEFAULT_TOP_K")
    retrieval_max_top_k: int = Field(40, ge=1, le=40, alias="RETRIEVAL_MAX_TOP_K")
    retrieval_cache_ttl_seconds: int = Field(300, alias="RETRIEVAL_CACHE_TTL_SECONDS")
    retrieval_cache_enabled: bool = Field(True, alias="RETRIEVAL_CACHE_ENABLED")
    retrieval_min_score: float | None = Field(0.2, alias="RETRIEVAL_MIN_SCORE")
    retrieval_raw_min_score: float | None = Field(None, alias="RETRIEVAL_RAW_MIN_SCORE")
    retrieval_rank_fusion_min_score: float | None = Field(
        None, alias="RETRIEVAL_RANK_FUSION_MIN_SCORE"
    )
    retrieval_rerank_min_score: float | None = Field(
        None, alias="RETRIEVAL_RERANK_MIN_SCORE"
    )
    retrieval_query_lowercase: bool = Field(False, alias="RETRIEVAL_QUERY_LOWERCASE")
    retrieval_hybrid_rrf_k: int = Field(60, alias="RETRIEVAL_HYBRID_RRF_K")
    retrieval_query_rewrite_max_tokens: int = Field(
        64, alias="RETRIEVAL_QUERY_REWRITE_MAX_TOKENS"
    )
    retrieval_rerank_base_url: str = Field(
        "https://api.openai.com", alias="RETRIEVAL_RERANK_BASE_URL"
    )
    retrieval_rerank_api_key: str = Field(
        "REPLACE_ME", alias="RETRIEVAL_RERANK_API_KEY"
    )
    retrieval_rerank_model: str = Field(
        "BAAI/bge-reranker-v2-m3", alias="RETRIEVAL_RERANK_MODEL"
    )
    retrieval_rerank_timeout_seconds: int = Field(
        10, alias="RETRIEVAL_RERANK_TIMEOUT_SECONDS"
    )
    retrieval_rerank_max_documents_per_request: int | None = Field(
        None,
        ge=1,
        alias="RETRIEVAL_RERANK_MAX_DOCUMENTS_PER_REQUEST",
    )

    context_history_max_messages: int = Field(6, alias="CONTEXT_HISTORY_MAX_MESSAGES")
    context_history_max_tokens: int | None = Field(
        4_000, alias="CONTEXT_HISTORY_MAX_TOKENS"
    )
    context_tool_max_tokens: int | None = Field(
        2_000, alias="CONTEXT_TOOL_MAX_TOKENS"
    )
    context_retrieval_max_tokens: int | None = Field(
        16_000, alias="CONTEXT_RETRIEVAL_MAX_TOKENS"
    )

    kb_chat_graph_recursion_limit: int = Field(
        30, alias="KB_CHAT_GRAPH_RECURSION_LIMIT"
    )
    kb_chat_max_total_rounds: int = Field(3, alias="KB_CHAT_MAX_TOTAL_ROUNDS")
    kb_chat_max_retrieval_retries: int = Field(2, alias="KB_CHAT_MAX_RETRIEVAL_RETRIES")
    kb_chat_max_generation_retries: int = Field(
        1, alias="KB_CHAT_MAX_GENERATION_RETRIES"
    )
    kb_chat_draft_max_tokens: int = Field(
        2_048, ge=1, alias="KB_CHAT_DRAFT_MAX_TOKENS"
    )
    kb_chat_repair_max_tokens: int = Field(
        1_500, ge=1, alias="KB_CHAT_REPAIR_MAX_TOKENS"
    )
    kb_chat_plain_fallback_max_tokens: int = Field(
        1_500, ge=1, alias="KB_CHAT_PLAIN_FALLBACK_MAX_TOKENS"
    )
    kb_chat_run_model_call_limit: int | None = Field(
        24, ge=1, alias="KB_CHAT_RUN_MODEL_CALL_LIMIT"
    )
    kb_chat_fallback_model_id: str | None = Field(
        None, alias="KB_CHAT_FALLBACK_MODEL_ID"
    )
    tool_selector_enabled: bool = Field(True, alias="TOOL_SELECTOR_ENABLED")
    tool_selector_trigger_tool_count: int = Field(
        10, ge=1, alias="TOOL_SELECTOR_TRIGGER_TOOL_COUNT"
    )
    tool_selector_max_tools: int = Field(5, ge=1, alias="TOOL_SELECTOR_MAX_TOOLS")
    tool_selector_model_id: str | None = Field(None, alias="TOOL_SELECTOR_MODEL_ID")
    tool_selector_always_include: list[str] = Field(
        default_factory=list,
        alias="TOOL_SELECTOR_ALWAYS_INCLUDE",
    )
    deep_research_thread_model_call_limit: int | None = Field(
        240, ge=1, alias="DEEP_RESEARCH_THREAD_MODEL_CALL_LIMIT"
    )
    deep_research_run_model_call_limit: int | None = Field(
        120, ge=1, alias="DEEP_RESEARCH_RUN_MODEL_CALL_LIMIT"
    )
    deep_research_fallback_model_id: str | None = Field(
        None, alias="DEEP_RESEARCH_FALLBACK_MODEL_ID"
    )
    deep_research_large_result_max_inline_chars: int = Field(
        2_000, ge=1, alias="DEEP_RESEARCH_LARGE_RESULT_MAX_INLINE_CHARS"
    )
    deep_research_priority_inline_chars: int = Field(
        12_000, ge=1, alias="DEEP_RESEARCH_PRIORITY_INLINE_CHARS"
    )
    anthropic_prompt_caching_enabled: bool = Field(
        True, alias="ANTHROPIC_PROMPT_CACHING_ENABLED"
    )
    anthropic_prompt_cache_ttl: str = Field(
        "5m", alias="ANTHROPIC_PROMPT_CACHE_TTL"
    )
    anthropic_prompt_cache_min_messages: int = Field(
        0, ge=0, alias="ANTHROPIC_PROMPT_CACHE_MIN_MESSAGES"
    )
    kb_chat_grader_fail_policy: str = Field(
        "closed", alias="KB_CHAT_GRADER_FAIL_POLICY"
    )
    kb_chat_json_safe_policy: str = Field("stringify", alias="KB_CHAT_JSON_SAFE_POLICY")
    kb_chat_ambiguity_check_enabled: bool = Field(
        True, alias="KB_CHAT_AMBIGUITY_CHECK_ENABLED"
    )
    kb_chat_multi_query_mod_enabled: bool = Field(
        True, alias="KB_CHAT_MULTI_QUERY_MOD_ENABLED"
    )
    kb_chat_decomposition_enabled: bool = Field(
        True, alias="KB_CHAT_DECOMPOSITION_ENABLED"
    )
    kb_chat_multi_query_enabled: bool = Field(True, alias="KB_CHAT_MULTI_QUERY_ENABLED")
    kb_chat_max_clarification_rounds: int = Field(
        1, alias="KB_CHAT_MAX_CLARIFICATION_ROUNDS"
    )
    research_scoper_max_clarify_rounds: int = Field(
        2, ge=1, le=4, alias="RESEARCH_SCOPER_MAX_CLARIFY_ROUNDS"
    )
    kb_chat_complexity_cache_enabled: bool = Field(
        True, alias="KB_CHAT_COMPLEXITY_CACHE_ENABLED"
    )
    kb_chat_complexity_cache_ttl_seconds: int = Field(
        120, ge=0, alias="KB_CHAT_COMPLEXITY_CACHE_TTL_SECONDS"
    )
    kb_chat_semantic_cache_enabled: bool = Field(
        True, alias="KB_CHAT_SEMANTIC_CACHE_ENABLED"
    )
    kb_chat_semantic_cache_similarity_threshold: float = Field(
        0.88, ge=0.0, le=1.0, alias="KB_CHAT_SEMANTIC_CACHE_SIMILARITY_THRESHOLD"
    )
    kb_chat_semantic_cache_index_name: str = Field(
        "kb_chat_semantic_cache_v4", alias="KB_CHAT_SEMANTIC_CACHE_INDEX_NAME"
    )
    kb_chat_semantic_cache_ttl_seconds: int = Field(
        24 * 60 * 60, ge=0, alias="KB_CHAT_SEMANTIC_CACHE_TTL_SECONDS"
    )
    kb_chat_semantic_cache_recovery_cooldown_seconds: int = Field(
        30, ge=0, alias="KB_CHAT_SEMANTIC_CACHE_RECOVERY_COOLDOWN_SECONDS"
    )
    kb_chat_parallel_retrieval_min_queries: int = Field(
        2, ge=1, le=8, alias="KB_CHAT_PARALLEL_RETRIEVAL_MIN_QUERIES"
    )
    kb_chat_parallel_retrieval_max_branches: int = Field(
        6, ge=1, le=12, alias="KB_CHAT_PARALLEL_RETRIEVAL_MAX_BRANCHES"
    )
    kb_chat_parallel_retrieval_include_main: bool = Field(
        True, alias="KB_CHAT_PARALLEL_RETRIEVAL_INCLUDE_MAIN"
    )
    kb_chat_gray_release_auto_rollback_enabled: bool = Field(
        True, alias="KB_CHAT_GRAY_RELEASE_AUTO_ROLLBACK_ENABLED"
    )
    kb_chat_gray_release_window_size: int = Field(
        200, ge=20, le=2000, alias="KB_CHAT_GRAY_RELEASE_WINDOW_SIZE"
    )
    kb_chat_gray_release_rollback_cooldown_minutes: int = Field(
        30, ge=1, le=720, alias="KB_CHAT_GRAY_RELEASE_ROLLBACK_COOLDOWN_MINUTES"
    )
    kb_chat_trace_enabled: bool = Field(True, alias="KB_CHAT_TRACE_ENABLED")

    summary_enabled: bool = Field(True, alias="SUMMARY_ENABLED")
    summary_trigger_min_messages: int = Field(12, alias="SUMMARY_TRIGGER_MIN_MESSAGES")
    summary_trigger_min_tokens: int = Field(2_000, alias="SUMMARY_TRIGGER_MIN_TOKENS")
    summary_keep_messages: int = Field(20, alias="SUMMARY_KEEP_MESSAGES")
    summary_max_tokens: int = Field(400, alias="SUMMARY_MAX_TOKENS")
    summary_trim_tokens: int = Field(4_000, alias="SUMMARY_TRIM_TOKENS")

    ingestion_contextual_enabled: bool = Field(
        True, alias="INGESTION_CONTEXTUAL_ENABLED"
    )
    ingestion_contextual_max_tokens: int = Field(
        192, alias="INGESTION_CONTEXTUAL_MAX_TOKENS"
    )
    ingestion_contextual_concurrency: int = Field(
        2, alias="INGESTION_CONTEXTUAL_CONCURRENCY"
    )
    ingestion_embedding_batch_size: int = Field(
        32, alias="INGESTION_EMBEDDING_BATCH_SIZE"
    )
    ingestion_embedding_fanout_concurrency: int = Field(
        4, ge=1, alias="INGESTION_EMBEDDING_FANOUT_CONCURRENCY"
    )
    index_rebuild_material_concurrency: int = Field(
        2, ge=1, alias="INDEX_REBUILD_MATERIAL_CONCURRENCY"
    )
    ingestion_doc_queue_timeout_seconds: int = Field(
        600, ge=1, alias="INGESTION_DOC_QUEUE_TIMEOUT_SECONDS"
    )
    ingestion_outbox_stale_dispatched_seconds: int = Field(
        300, ge=1, alias="INGESTION_OUTBOX_STALE_DISPATCHED_SECONDS"
    )
    frontend_status_polling_interval_ms: int = Field(
        2_000, ge=100, alias="FRONTEND_STATUS_POLLING_INTERVAL_MS"
    )
    frontend_ingestion_stream_fallback_polling_steps_ms: list[int] = Field(
        default_factory=lambda: [1_000, 2_000, 5_000],
        alias="FRONTEND_INGESTION_STREAM_FALLBACK_POLLING_STEPS_MS",
    )
    frontend_ingestion_stream_retry_multiplier: int = Field(
        2, ge=1, alias="FRONTEND_INGESTION_STREAM_RETRY_MULTIPLIER"
    )
    frontend_export_poll_interval_ms: int = Field(
        2_000, ge=100, alias="FRONTEND_EXPORT_POLL_INTERVAL_MS"
    )
    frontend_export_poll_max_attempts: int = Field(
        60, ge=1, alias="FRONTEND_EXPORT_POLL_MAX_ATTEMPTS"
    )
    frontend_server_prefetch_cache_revalidate_seconds: int = Field(
        30, ge=0, alias="FRONTEND_SERVER_PREFETCH_CACHE_REVALIDATE_SECONDS"
    )
    frontend_download_allowed_hosts: list[str] = Field(
        default_factory=list,
        alias="FRONTEND_DOWNLOAD_ALLOWED_HOSTS",
    )

    @property
    def retrieval_rerank_configured(self) -> bool:
        base_url = str(self.retrieval_rerank_base_url or "").strip().rstrip("/")
        api_key = str(self.retrieval_rerank_api_key or "").strip()
        model = str(self.retrieval_rerank_model or "").strip()
        if not base_url or not model or not api_key:
            return False
        if api_key.upper() == "REPLACE_ME":
            return False
        return not (
            base_url == "https://api.openai.com"
            and model == "BAAI/bge-reranker-v2-m3"
        )

    ingestion_url_max_redirects: int = Field(3, alias="INGESTION_URL_MAX_REDIRECTS")
    ingestion_url_timeout_seconds: float = Field(
        25.0, alias="INGESTION_URL_TIMEOUT_SECONDS"
    )
    ingestion_url_max_bytes: int = Field(
        20 * 1024 * 1024, alias="INGESTION_URL_MAX_BYTES"
    )
    ingestion_url_user_agent: str = Field(
        "multi-kb-agent/ingestion", alias="INGESTION_URL_USER_AGENT"
    )
    ingestion_url_blocked_cidrs_v4: list[str] = Field(
        default_factory=lambda: DEFAULT_INGESTION_BLOCKED_CIDRS_V4.copy(),
        alias="INGESTION_URL_BLOCKED_CIDRS_V4",
    )
    ingestion_url_blocked_cidrs_v6: list[str] = Field(
        default_factory=lambda: DEFAULT_INGESTION_BLOCKED_CIDRS_V6.copy(),
        alias="INGESTION_URL_BLOCKED_CIDRS_V6",
    )
    ingestion_url_metadata_blocklist: list[str] = Field(
        default_factory=lambda: DEFAULT_INGESTION_METADATA_BLOCKLIST.copy(),
        alias="INGESTION_URL_METADATA_BLOCKLIST",
    )

    mineru_model_source: str | None = Field(None, alias="MINERU_MODEL_SOURCE")
    mineru_lang: str = Field("ch", alias="MINERU_LANG")
    mineru_parse_method: str = Field("auto", alias="MINERU_PARSE_METHOD")
    mineru_formula_enable: bool = Field(True, alias="MINERU_FORMULA_ENABLE")
    mineru_table_enable: bool = Field(True, alias="MINERU_TABLE_ENABLE")
    pdf_fallback_enabled: bool = Field(True, alias="PDF_FALLBACK_ENABLED")
    pdf_fallback_max_pages: int = Field(500, ge=1, alias="PDF_FALLBACK_MAX_PAGES")
    pdf_fallback_min_text_chars: int = Field(
        20, ge=0, alias="PDF_FALLBACK_MIN_TEXT_CHARS"
    )

    @field_validator("mineru_parse_method", mode="before")
    @classmethod
    def _normalize_mineru_parse_method(cls, value: object) -> str:
        raw = str(value or "auto").strip().lower()
        if raw in {"auto", "txt", "ocr"}:
            return raw
        return "auto"

    @field_validator(
        "ingestion_url_blocked_cidrs_v4",
        "ingestion_url_blocked_cidrs_v6",
        "ingestion_url_metadata_blocklist",
        "frontend_download_allowed_hosts",
        mode="before",
    )
    @classmethod
    def _parse_ingestion_url_lists(cls, value: object) -> list[str]:
        return parse_string_list(value)

    @field_validator(
        "frontend_ingestion_stream_fallback_polling_steps_ms",
        mode="before",
    )
    @classmethod
    def _parse_frontend_polling_steps(cls, value: object) -> list[int]:
        parsed = parse_string_list(value)
        if not parsed:
            return [1_000, 2_000, 5_000]
        return [int(item) for item in parsed]

    @field_validator("frontend_download_allowed_hosts", mode="after")
    @classmethod
    def _normalize_frontend_download_allowed_hosts(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            host = item.strip().lower()
            if not host or host in seen:
                continue
            seen.add(host)
            normalized.append(host)
        return normalized

    @field_validator("milvus_text_analyzer_filters", mode="before")
    @classmethod
    def _parse_analyzer_filters(cls, value: object) -> list[str]:
        return parse_string_list(value)

    @field_validator("tool_selector_always_include", mode="before")
    @classmethod
    def _parse_tool_selector_always_include(cls, value: object) -> list[str]:
        return parse_string_list(value)

    @field_validator("memory_store_url", "jina_read_base_url", mode="before")
    @classmethod
    def _normalize_local_optional_urls(cls, value: object) -> object:
        if value is None:
            return value
        return prefer_ipv4_loopback_url(str(value))

    @field_validator("milvus_host", mode="before")
    @classmethod
    def _normalize_milvus_host(cls, value: object) -> object:
        if value is None:
            return value
        raw = str(value).strip()
        if sys.platform.startswith("win") and raw == "localhost":
            return "127.0.0.1"
        return raw

    @field_validator("kb_chat_grader_fail_policy", mode="before")
    @classmethod
    def _normalize_kb_chat_grader_fail_policy(cls, value: object) -> str:
        raw = "closed" if value is None else str(value)
        normalized = raw.strip().lower()
        if normalized not in {"open", "closed"}:
            raise ValueError("KB_CHAT_GRADER_FAIL_POLICY must be 'open' or 'closed'")
        return normalized

    @field_validator("kb_chat_json_safe_policy", mode="before")
    @classmethod
    def _normalize_kb_chat_json_safe_policy(cls, value: object) -> str:
        raw = "stringify" if value is None else str(value)
        normalized = raw.strip().lower().replace("-", "_")
        if normalized not in {"fail_fast", "stringify"}:
            raise ValueError(
                "KB_CHAT_JSON_SAFE_POLICY must be 'fail_fast' or 'stringify'"
            )
        return normalized

    @field_validator("llm_output_version", mode="before")
    @classmethod
    def _normalize_llm_output_version(cls, value: object) -> str:
        raw = "responses/v1" if value is None else str(value)
        normalized = raw.strip().lower()
        if normalized not in {"v0", "v1", "responses/v1"}:
            raise ValueError("LLM_OUTPUT_VERSION must be one of: v0, v1, responses/v1")
        return normalized

    @field_validator("general_chat_replay_mode", mode="before")
    @classmethod
    def _normalize_general_chat_replay_mode(cls, value: object) -> str:
        raw = "auto" if value is None else str(value)
        normalized = raw.strip().lower()
        if normalized not in {"auto", "response_id", "manual"}:
            raise ValueError(
                "GENERAL_CHAT_REPLAY_MODE must be one of: auto, response_id, manual"
            )
        return normalized

    @field_validator("anthropic_prompt_cache_ttl", mode="before")
    @classmethod
    def _normalize_anthropic_prompt_cache_ttl(cls, value: object) -> str:
        raw = "5m" if value is None else str(value)
        normalized = raw.strip().lower()
        if normalized not in {"5m", "1h"}:
            raise ValueError("ANTHROPIC_PROMPT_CACHE_TTL must be '5m' or '1h'")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
