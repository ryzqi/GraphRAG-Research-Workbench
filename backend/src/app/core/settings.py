from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]
ENV_FILE = ROOT_DIR / ".env"

_IPV4_LOOPBACK = "127.0.0.1"

# Keep only Next.js dev origins on port 3000.
_DEV_LOCAL_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

_LEGACY_VITE_LOCAL_CORS_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

_DEFAULT_INGESTION_BLOCKED_CIDRS_V4 = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
]

_DEFAULT_INGESTION_BLOCKED_CIDRS_V6 = [
    "::/128",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

_DEFAULT_INGESTION_METADATA_BLOCKLIST = [
    "169.254.169.254",
]

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://mkb:mkb_password@localhost:5432/mkb"
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_DEFAULT_CELERY_BROKER_URL = "redis://localhost:6379/0"
_DEFAULT_CELERY_RESULT_BACKEND = "redis://localhost:6379/1"
_DEFAULT_MINIO_ACCESS_KEY = "minioadmin"
_DEFAULT_MINIO_SECRET_KEY = "minioadmin"


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _parse_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return _dedupe_keep_order([str(item) for item in value])
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            else:
                if isinstance(parsed, list):
                    return _dedupe_keep_order([str(item) for item in parsed])
        parts = [part.strip().strip('"').strip("'") for part in raw.split(",")]
        return _dedupe_keep_order(parts)
    return _dedupe_keep_order([str(value)])


def _prefer_ipv4_loopback_url(value: str) -> str:
    """Prefer IPv4 loopback when a URL uses 'localhost' on Windows.

    On Windows, some clients may try IPv6 (::1) first for 'localhost'. For services that
    only listen on IPv4 (common with Podman port forwarding), this can lead to long
    connection delays or timeouts. Rewriting to 127.0.0.1 avoids the issue.
    """

    if not value:
        return value
    if not sys.platform.startswith("win"):
        return value

    try:
        parts = urlsplit(value)
    except Exception:
        return value

    if parts.hostname != "localhost":
        return value

    userinfo = ""
    if parts.username is not None:
        userinfo = quote(parts.username, safe="")
        if parts.password is not None:
            userinfo += ":" + quote(parts.password, safe="")
        userinfo += "@"

    port = f":{parts.port}" if parts.port else ""
    netloc = f"{userinfo}{_IPV4_LOOPBACK}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _prefer_ipv4_loopback_hostport(value: str) -> str:
    """Prefer IPv4 loopback when a host[:port] string uses 'localhost' on Windows."""

    if not value:
        return value
    if not sys.platform.startswith("win"):
        return value

    raw = value.strip()
    if not raw:
        return value

    # minio uses host[:port] (not a URL), so we do a simple prefix replace.
    if raw == "localhost":
        return _IPV4_LOOPBACK
    if raw.startswith("localhost:"):
        return _IPV4_LOOPBACK + raw[len("localhost") :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "多知识库知识代理"
    app_env: str = Field("dev", alias="APP_ENV")
    app_log_level: str = Field("INFO", alias="APP_LOG_LEVEL")
    app_cors_allow_origins: list[str] = Field(
        default_factory=lambda: _DEV_LOCAL_CORS_ORIGINS.copy(),
        alias="APP_CORS_ALLOW_ORIGINS",
    )

    database_url: str = Field(
        _DEFAULT_DATABASE_URL,
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(10, alias="DB_MAX_OVERFLOW")
    db_pool_recycle_seconds: int = Field(1800, alias="DB_POOL_RECYCLE_SECONDS")

    redis_url: str = Field(_DEFAULT_REDIS_URL, alias="REDIS_URL")
    redis_socket_timeout_seconds: float = Field(
        1.0, alias="REDIS_SOCKET_TIMEOUT_SECONDS"
    )
    redis_socket_connect_timeout_seconds: float = Field(
        1.0, alias="REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS"
    )
    celery_broker_url: str = Field(
        _DEFAULT_CELERY_BROKER_URL, alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        _DEFAULT_CELERY_RESULT_BACKEND, alias="CELERY_RESULT_BACKEND"
    )
    celery_broker_visibility_timeout_seconds: int = Field(
        7_200, ge=1, alias="CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS"
    )
    celery_task_soft_time_limit_seconds: int = Field(
        0, ge=0, alias="CELERY_TASK_SOFT_TIME_LIMIT_SECONDS"
    )
    celery_task_time_limit_seconds: int = Field(
        0, ge=0, alias="CELERY_TASK_TIME_LIMIT_SECONDS"
    )
    celery_task_store_errors_even_if_ignored: bool = Field(
        True, alias="CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED"
    )
    celery_worker_send_task_events: bool = Field(
        False, alias="CELERY_WORKER_SEND_TASK_EVENTS"
    )
    celery_task_send_sent_event: bool = Field(
        False, alias="CELERY_TASK_SEND_SENT_EVENT"
    )
    celery_worker_prefetch_multiplier: int = Field(
        1, ge=1, alias="CELERY_WORKER_PREFETCH_MULTIPLIER"
    )

    http_timeout_connect_seconds: float = Field(
        5.0, alias="HTTP_TIMEOUT_CONNECT_SECONDS"
    )
    http_timeout_read_seconds: float = Field(30.0, alias="HTTP_TIMEOUT_READ_SECONDS")
    http_timeout_write_seconds: float = Field(30.0, alias="HTTP_TIMEOUT_WRITE_SECONDS")
    http_timeout_pool_seconds: float = Field(5.0, alias="HTTP_TIMEOUT_POOL_SECONDS")
    http_max_connections: int = Field(100, alias="HTTP_MAX_CONNECTIONS")
    http_max_keepalive_connections: int = Field(
        20, alias="HTTP_MAX_KEEPALIVE_CONNECTIONS"
    )
    http_keepalive_expiry_seconds: float = Field(
        5.0, alias="HTTP_KEEPALIVE_EXPIRY_SECONDS"
    )

    milvus_host: str = Field("localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(19530, alias="MILVUS_PORT")
    milvus_collection: str = Field("kb_chunks_v1", alias="MILVUS_COLLECTION")
    milvus_text_analyzer: str = Field("chinese", alias="MILVUS_TEXT_ANALYZER")
    milvus_text_analyzer_filters: list[str] = Field(
        default_factory=list, alias="MILVUS_TEXT_ANALYZER_FILTERS"
    )

    llm_timeout_seconds: float = Field(30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_input_tokens: int | None = Field(None, alias="LLM_MAX_INPUT_TOKENS")
    llm_output_version: str = Field("responses/v1", alias="LLM_OUTPUT_VERSION")
    general_chat_replay_mode: str = Field("auto", alias="GENERAL_CHAT_REPLAY_MODE")
    model_config_kms_key: str | None = Field(None, alias="MODEL_CONFIG_KMS_KEY")

    embedding_base_url: str = Field(
        "https://api.openai.com/v1", alias="EMBEDDING_BASE_URL"
    )
    embedding_api_key: str = Field("REPLACE_ME", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_timeout_seconds: float = Field(30.0, alias="EMBEDDING_TIMEOUT_SECONDS")
    embedding_dim: int | None = Field(None, alias="EMBEDDING_DIM")

    minio_endpoint: str = Field("localhost:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(_DEFAULT_MINIO_ACCESS_KEY, alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(_DEFAULT_MINIO_SECRET_KEY, alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(False, alias="MINIO_SECURE")
    minio_bucket_uploads: str = Field("mkb-uploads", alias="MINIO_BUCKET_UPLOADS")
    minio_bucket_exports: str = Field("mkb-exports", alias="MINIO_BUCKET_EXPORTS")
    bootstrap_upload_presign_expire_seconds: int = Field(
        900, alias="BOOTSTRAP_UPLOAD_PRESIGN_EXPIRE_SECONDS"
    )
    bootstrap_queued_timeout_seconds: int = Field(
        180, ge=1, alias="BOOTSTRAP_QUEUED_TIMEOUT_SECONDS"
    )
    exports_presign_expire_seconds: int = Field(
        3600, alias="EXPORTS_PRESIGN_EXPIRE_SECONDS"
    )

    mcp_enabled: bool = Field(False, alias="MCP_ENABLED")
    mcp_streamable_http: bool = Field(False, alias="MCP_STREAMABLE_HTTP")
    mcp_http_timeout_seconds: int = Field(30, alias="MCP_HTTP_TIMEOUT_SECONDS")
    mcp_stdio_timeout_seconds: int = Field(10, alias="MCP_STDIO_TIMEOUT_SECONDS")
    mcp_stdio_templates: dict[str, dict[str, object]] = Field(
        default_factory=dict, alias="MCP_STDIO_TEMPLATES"
    )

    deepagents_enabled: bool = Field(True, alias="DEEPAGENTS_ENABLED")
    memory_enabled: bool = Field(False, alias="MEMORY_ENABLED")
    memory_store_backend: str = Field("postgres", alias="MEMORY_STORE_BACKEND")
    memory_store_url: str | None = Field(None, alias="MEMORY_STORE_URL")
    memory_store_path: str = Field("/memories/", alias="MEMORY_STORE_PATH")

    # Web 搜索（Tavily，可选）
    web_search_api_key: str | None = Field(None, alias="WEB_SEARCH_API_KEY")
    web_search_cache_enabled: bool = Field(True, alias="WEB_SEARCH_CACHE_ENABLED")
    web_search_cache_ttl_seconds: int = Field(300, alias="WEB_SEARCH_CACHE_TTL_SECONDS")
    web_search_timeout_seconds: float = Field(60.0, alias="WEB_SEARCH_TIMEOUT_SECONDS")
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
        "markdown", alias="WEB_RESEARCH_CITATION_FORMAT"
    )
    web_research_output_schema: str | None = Field(
        None, alias="WEB_RESEARCH_OUTPUT_SCHEMA"
    )
    web_research_model: str | None = Field(None, alias="WEB_RESEARCH_MODEL")
    web_research_poll_interval_seconds: float = Field(
        2.0, alias="WEB_RESEARCH_POLL_INTERVAL_SECONDS"
    )
    web_research_timeout_seconds: float = Field(
        180.0, alias="WEB_RESEARCH_TIMEOUT_SECONDS"
    )

    # 检索配置
    retrieval_default_top_k: int = Field(12, alias="RETRIEVAL_DEFAULT_TOP_K")
    retrieval_max_top_k: int = Field(50, alias="RETRIEVAL_MAX_TOP_K")
    retrieval_cache_ttl_seconds: int = Field(300, alias="RETRIEVAL_CACHE_TTL_SECONDS")
    retrieval_cache_enabled: bool = Field(True, alias="RETRIEVAL_CACHE_ENABLED")
    retrieval_min_score: float | None = Field(0.2, alias="RETRIEVAL_MIN_SCORE")
    retrieval_query_lowercase: bool = Field(False, alias="RETRIEVAL_QUERY_LOWERCASE")
    retrieval_hybrid_enabled: bool = Field(True, alias="RETRIEVAL_HYBRID_ENABLED")
    retrieval_hybrid_ranker: str = Field("rrf", alias="RETRIEVAL_HYBRID_RANKER")
    retrieval_hybrid_dense_weight: float = Field(
        0.6, alias="RETRIEVAL_HYBRID_DENSE_WEIGHT"
    )
    retrieval_hybrid_sparse_weight: float = Field(
        0.4, alias="RETRIEVAL_HYBRID_SPARSE_WEIGHT"
    )
    retrieval_hybrid_rrf_k: int = Field(60, alias="RETRIEVAL_HYBRID_RRF_K")
    retrieval_query_rewrite_enabled: bool = Field(
        True, alias="RETRIEVAL_QUERY_REWRITE_ENABLED"
    )
    retrieval_query_rewrite_timeout_seconds: int = Field(
        15, alias="RETRIEVAL_QUERY_REWRITE_TIMEOUT_SECONDS"
    )
    retrieval_query_rewrite_max_tokens: int = Field(
        64, alias="RETRIEVAL_QUERY_REWRITE_MAX_TOKENS"
    )
    retrieval_rerank_enabled: bool = Field(True, alias="RETRIEVAL_RERANK_ENABLED")
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

    # 上下文预算配置
    context_history_max_messages: int = Field(6, alias="CONTEXT_HISTORY_MAX_MESSAGES")
    context_history_max_tokens: int | None = Field(
        None, alias="CONTEXT_HISTORY_MAX_TOKENS"
    )
    context_retrieval_max_tokens: int | None = Field(
        None, alias="CONTEXT_RETRIEVAL_MAX_TOKENS"
    )
    context_tool_max_tokens: int | None = Field(None, alias="CONTEXT_TOOL_MAX_TOKENS")

    # KB Chat（灰度开关 + 预算 + 查询增强 + 可观测）
    kb_chat_graph_recursion_limit: int = Field(
        30, alias="KB_CHAT_GRAPH_RECURSION_LIMIT"
    )
    kb_chat_max_total_rounds: int = Field(3, alias="KB_CHAT_MAX_TOTAL_ROUNDS")
    kb_chat_max_retrieval_retries: int = Field(2, alias="KB_CHAT_MAX_RETRIEVAL_RETRIES")
    kb_chat_max_generation_retries: int = Field(
        1, alias="KB_CHAT_MAX_GENERATION_RETRIES"
    )
    kb_chat_grader_fail_policy: str = Field(
        "closed", alias="KB_CHAT_GRADER_FAIL_POLICY"
    )
    kb_chat_json_safe_policy: str = Field("stringify", alias="KB_CHAT_JSON_SAFE_POLICY")

    kb_chat_ambiguity_check_enabled: bool = Field(
        True, alias="KB_CHAT_AMBIGUITY_CHECK_ENABLED"
    )
    kb_chat_ambiguity_timeout_seconds: float = Field(
        0.5, alias="KB_CHAT_AMBIGUITY_TIMEOUT_SECONDS"
    )
    kb_chat_normalize_llm_enabled: bool = Field(
        True, alias="KB_CHAT_NORMALIZE_LLM_ENABLED"
    )
    kb_chat_normalize_alias_max: int = Field(
        4, ge=1, le=8, alias="KB_CHAT_NORMALIZE_ALIAS_MAX"
    )
    kb_chat_normalize_timeout_seconds: float = Field(
        0.8, ge=0.0, le=5.0, alias="KB_CHAT_NORMALIZE_TIMEOUT_SECONDS"
    )
    kb_chat_max_clarification_rounds: int = Field(
        1, alias="KB_CHAT_MAX_CLARIFICATION_ROUNDS"
    )
    kb_chat_hyde_enabled: bool = Field(False, alias="KB_CHAT_HYDE_ENABLED")
    kb_chat_complexity_model_timeout_seconds: float = Field(
        1.5, ge=0.0, le=10.0, alias="KB_CHAT_COMPLEXITY_MODEL_TIMEOUT_SECONDS"
    )
    kb_chat_complexity_cache_enabled: bool = Field(
        True, alias="KB_CHAT_COMPLEXITY_CACHE_ENABLED"
    )
    kb_chat_complexity_cache_ttl_seconds: int = Field(
        120, ge=0, alias="KB_CHAT_COMPLEXITY_CACHE_TTL_SECONDS"
    )
    kb_chat_parallel_retrieval_enabled: bool = Field(
        True, alias="KB_CHAT_PARALLEL_RETRIEVAL_ENABLED"
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
    kb_chat_doc_gate_rule_threshold: float = Field(
        0.45, ge=0.0, le=1.0, alias="KB_CHAT_DOC_GATE_RULE_THRESHOLD"
    )
    kb_chat_doc_gate_llm_confidence_floor: float = Field(
        0.45, ge=0.0, le=1.0, alias="KB_CHAT_DOC_GATE_LLM_CONFIDENCE_FLOOR"
    )
    kb_chat_doc_gate_fallback_open_when_evidence_ok: bool = Field(
        True, alias="KB_CHAT_DOC_GATE_FALLBACK_OPEN_WHEN_EVIDENCE_OK"
    )
    kb_chat_doc_gate_cache_ttl_seconds: int = Field(
        60, ge=0, alias="KB_CHAT_DOC_GATE_CACHE_TTL_SECONDS"
    )

    kb_chat_trace_enabled: bool = Field(True, alias="KB_CHAT_TRACE_ENABLED")

    # 对话摘要配置
    summary_enabled: bool = Field(False, alias="SUMMARY_ENABLED")
    summary_trigger_min_messages: int = Field(12, alias="SUMMARY_TRIGGER_MIN_MESSAGES")
    summary_trigger_min_tokens: int = Field(800, alias="SUMMARY_TRIGGER_MIN_TOKENS")
    summary_max_tokens: int = Field(256, alias="SUMMARY_MAX_TOKENS")

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
    ingestion_doc_queue_timeout_seconds: int = Field(
        600, ge=1, alias="INGESTION_DOC_QUEUE_TIMEOUT_SECONDS"
    )
    ingestion_outbox_stale_dispatched_seconds: int = Field(
        300, ge=1, alias="INGESTION_OUTBOX_STALE_DISPATCHED_SECONDS"
    )

    # 导入：URL 抓取/正文抽取配置（最小安全基线）
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
        default_factory=lambda: _DEFAULT_INGESTION_BLOCKED_CIDRS_V4.copy(),
        alias="INGESTION_URL_BLOCKED_CIDRS_V4",
    )
    ingestion_url_blocked_cidrs_v6: list[str] = Field(
        default_factory=lambda: _DEFAULT_INGESTION_BLOCKED_CIDRS_V6.copy(),
        alias="INGESTION_URL_BLOCKED_CIDRS_V6",
    )
    ingestion_url_metadata_blocklist: list[str] = Field(
        default_factory=lambda: _DEFAULT_INGESTION_METADATA_BLOCKLIST.copy(),
        alias="INGESTION_URL_METADATA_BLOCKLIST",
    )

    # PDF 解析（MinerU + 文本兜底）
    mineru_model_source: str | None = Field(None, alias="MINERU_MODEL_SOURCE")
    mineru_lang: str = Field("ch", alias="MINERU_LANG")
    mineru_parse_method: str = Field("auto", alias="MINERU_PARSE_METHOD")
    mineru_formula_enable: bool = Field(True, alias="MINERU_FORMULA_ENABLE")
    mineru_table_enable: bool = Field(True, alias="MINERU_TABLE_ENABLE")
    pdf_fallback_enabled: bool = Field(True, alias="PDF_FALLBACK_ENABLED")
    pdf_fallback_max_pages: int = Field(500, ge=1, alias="PDF_FALLBACK_MAX_PAGES")
    pdf_fallback_min_text_chars: int = Field(20, ge=0, alias="PDF_FALLBACK_MIN_TEXT_CHARS")

    # OpenTelemetry 配置
    otel_enabled: bool = Field(False, alias="OTEL_ENABLED")
    otel_endpoint: str | None = Field(None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field("multi-kb-agent", alias="OTEL_SERVICE_NAME")

    @field_validator(
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
        mode="before",
    )
    @classmethod
    def _normalize_localhost_urls(cls, v: object) -> object:
        if v is None:
            return v
        return _prefer_ipv4_loopback_url(str(v))

    @field_validator("minio_endpoint", mode="before")
    @classmethod
    def _normalize_minio_endpoint(cls, v: object) -> object:
        if v is None:
            return v
        return _prefer_ipv4_loopback_hostport(str(v))

    @field_validator("milvus_host", mode="before")
    @classmethod
    def _normalize_milvus_host(cls, v: object) -> object:
        if v is None:
            return v
        raw = str(v)
        if sys.platform.startswith("win") and raw.strip() == "localhost":
            return _IPV4_LOOPBACK
        return raw

    @field_validator("mineru_parse_method", mode="before")
    @classmethod
    def _normalize_mineru_parse_method(cls, v: object) -> str:
        raw = str(v or "auto").strip().lower()
        if raw in {"auto", "txt", "ocr"}:
            return raw
        return "auto"

    @field_validator("app_cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> list[str]:
        if v is None:
            return _DEV_LOCAL_CORS_ORIGINS.copy()
        if isinstance(v, list):
            return _dedupe_keep_order([str(x) for x in v])
        if isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
                else:
                    if isinstance(parsed, list):
                        return _dedupe_keep_order([str(x) for x in parsed])
            parts = [p.strip().strip('"').strip("'") for p in raw.split(",")]
            return _dedupe_keep_order(parts)
        return _dedupe_keep_order([str(v)])

    @field_validator(
        "ingestion_url_blocked_cidrs_v4",
        "ingestion_url_blocked_cidrs_v6",
        "ingestion_url_metadata_blocklist",
        mode="before",
    )
    @classmethod
    def _parse_ingestion_url_lists(cls, v: object) -> list[str]:
        return _parse_string_list(v)

    @model_validator(mode="after")
    def _ensure_local_dev_cors_origins(self) -> "Settings":
        if _is_dev_env(self.app_env):
            custom_origins = [
                origin
                for origin in self.app_cors_allow_origins
                if origin not in _LEGACY_VITE_LOCAL_CORS_ORIGINS
            ]
            self.app_cors_allow_origins = _dedupe_keep_order(
                [*custom_origins, *_DEV_LOCAL_CORS_ORIGINS]
            )
        return self

    @model_validator(mode="after")
    def _validate_celery_time_limit_settings(self) -> "Settings":
        if (
            self.celery_task_soft_time_limit_seconds > 0
            and self.celery_task_time_limit_seconds > 0
            and self.celery_task_time_limit_seconds
            < self.celery_task_soft_time_limit_seconds
        ):
            raise ValueError(
                "CELERY_TASK_TIME_LIMIT_SECONDS must be >= "
                "CELERY_TASK_SOFT_TIME_LIMIT_SECONDS"
            )
        return self

    @field_validator("milvus_text_analyzer_filters", mode="before")
    @classmethod
    def _parse_analyzer_filters(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",")]
            return [p for p in parts if p]
        return [str(v).strip()]

    @field_validator("mcp_stdio_templates", mode="before")
    @classmethod
    def _parse_mcp_stdio_templates(cls, v: object) -> dict[str, dict[str, object]]:
        if v is None:
            return {}
        raw: object = v
        if isinstance(v, str):
            text = v.strip()
            if not text:
                return {}
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("MCP_STDIO_TEMPLATES must be valid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError("MCP_STDIO_TEMPLATES must be a JSON object")

        templates: dict[str, dict[str, object]] = {}
        for template_id, config in raw.items():
            key = str(template_id).strip()
            if not key:
                continue
            if not isinstance(config, dict):
                raise ValueError(f"stdio template '{key}' must be an object")
            command = str(config.get("command", "")).strip()
            if not command:
                raise ValueError(f"stdio template '{key}' requires command")
            args_raw = config.get("args", [])
            if args_raw is None:
                args_raw = []
            if not isinstance(args_raw, list):
                raise ValueError(f"stdio template '{key}'.args must be an array")
            env_raw = config.get("env", {})
            if env_raw is None:
                env_raw = {}
            if not isinstance(env_raw, dict):
                raise ValueError(f"stdio template '{key}'.env must be an object")
            label = str(config.get("label", key)).strip() or key
            description_raw = config.get("description")
            description = (
                str(description_raw).strip()
                if isinstance(description_raw, str) and description_raw.strip()
                else None
            )
            templates[key] = {
                "command": command,
                "args": [str(item) for item in args_raw],
                "env": {str(k): str(v) for k, v in env_raw.items()},
                "label": label,
                "description": description,
            }
        return templates

    @field_validator("kb_chat_grader_fail_policy", mode="before")
    @classmethod
    def _normalize_kb_chat_grader_fail_policy(cls, v: object) -> str:
        raw = "closed" if v is None else str(v)
        normalized = raw.strip().lower()
        if normalized not in {"open", "closed"}:
            raise ValueError("KB_CHAT_GRADER_FAIL_POLICY must be 'open' or 'closed'")
        return normalized

    @field_validator("kb_chat_json_safe_policy", mode="before")
    @classmethod
    def _normalize_kb_chat_json_safe_policy(cls, v: object) -> str:
        raw = "stringify" if v is None else str(v)
        normalized = raw.strip().lower().replace("-", "_")
        if normalized not in {"fail_fast", "stringify"}:
            raise ValueError(
                "KB_CHAT_JSON_SAFE_POLICY must be 'fail_fast' or 'stringify'"
            )
        return normalized

    @field_validator("llm_output_version", mode="before")
    @classmethod
    def _normalize_llm_output_version(cls, v: object) -> str:
        raw = "responses/v1" if v is None else str(v)
        normalized = raw.strip().lower()
        if normalized not in {"v0", "v1", "responses/v1"}:
            raise ValueError(
                "LLM_OUTPUT_VERSION must be one of: v0, v1, responses/v1"
            )
        return normalized

    @field_validator("general_chat_replay_mode", mode="before")
    @classmethod
    def _normalize_general_chat_replay_mode(cls, v: object) -> str:
        raw = "auto" if v is None else str(v)
        normalized = raw.strip().lower()
        if normalized not in {"auto", "response_id", "manual"}:
            raise ValueError(
                "GENERAL_CHAT_REPLAY_MODE must be one of: auto, response_id, manual"
            )
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _is_dev_env(app_env: str) -> bool:
    return app_env.strip().lower() in {"dev", "development", "local", "test"}


def _normalize_url_for_compare(value: str) -> str:
    return _prefer_ipv4_loopback_url(value.strip())


def validate_startup_settings(settings: Settings) -> None:
    """启动期安全校验：避免危险默认配置进入非开发环境。"""
    if _is_dev_env(settings.app_env):
        return

    problems: list[str] = []

    embedding_key = settings.embedding_api_key.strip()
    if not embedding_key or embedding_key == "REPLACE_ME":
        problems.append("EMBEDDING_API_KEY 为空或为占位值（REPLACE_ME）")

    model_config_kms_key = (settings.model_config_kms_key or "").strip()
    if not model_config_kms_key:
        problems.append("MODEL_CONFIG_KMS_KEY 为空")

    if _normalize_url_for_compare(settings.database_url) == _normalize_url_for_compare(
        _DEFAULT_DATABASE_URL
    ):
        problems.append("DATABASE_URL 使用默认示例凭据（mkb/mkb_password）")

    if _normalize_url_for_compare(settings.redis_url) == _normalize_url_for_compare(
        _DEFAULT_REDIS_URL
    ):
        problems.append("REDIS_URL 使用默认示例配置")

    if _normalize_url_for_compare(settings.celery_broker_url) == _normalize_url_for_compare(
        _DEFAULT_CELERY_BROKER_URL
    ):
        problems.append("CELERY_BROKER_URL 使用默认示例配置")

    if _normalize_url_for_compare(
        settings.celery_result_backend
    ) == _normalize_url_for_compare(_DEFAULT_CELERY_RESULT_BACKEND):
        problems.append("CELERY_RESULT_BACKEND 使用默认示例配置")

    if (settings.minio_access_key or "").strip() == _DEFAULT_MINIO_ACCESS_KEY:
        problems.append("MINIO_ACCESS_KEY 使用默认值（minioadmin）")

    if (settings.minio_secret_key or "").strip() == _DEFAULT_MINIO_SECRET_KEY:
        problems.append("MINIO_SECRET_KEY 使用默认值（minioadmin）")

    if problems:
        raise RuntimeError(
            f"启动安全校验失败（APP_ENV={settings.app_env}）：{'; '.join(problems)}"
        )
