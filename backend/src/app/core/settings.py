from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]
ENV_FILE = ROOT_DIR / ".env"

_IPV4_LOOPBACK = "127.0.0.1"


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
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="APP_CORS_ALLOW_ORIGINS",
    )

    database_url: str = Field(
        "postgresql+asyncpg://mkb:mkb_password@localhost:5432/mkb",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(10, alias="DB_MAX_OVERFLOW")
    db_pool_recycle_seconds: int = Field(1800, alias="DB_POOL_RECYCLE_SECONDS")

    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    redis_socket_timeout_seconds: float = Field(
        1.0, alias="REDIS_SOCKET_TIMEOUT_SECONDS"
    )
    redis_socket_connect_timeout_seconds: float = Field(
        1.0, alias="REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS"
    )
    celery_broker_url: str = Field(
        "redis://localhost:6379/0", alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        "redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND"
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

    llm_base_url: str = Field("https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field("REPLACE_ME", alias="LLM_API_KEY")
    llm_model: str = Field("gpt-4o-mini", alias="LLM_MODEL")
    llm_timeout_seconds: float = Field(30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_input_tokens: int | None = Field(None, alias="LLM_MAX_INPUT_TOKENS")

    embedding_base_url: str = Field(
        "https://api.openai.com/v1", alias="EMBEDDING_BASE_URL"
    )
    embedding_api_key: str = Field("REPLACE_ME", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_timeout_seconds: float = Field(30.0, alias="EMBEDDING_TIMEOUT_SECONDS")
    embedding_dim: int | None = Field(None, alias="EMBEDDING_DIM")

    minio_endpoint: str = Field("localhost:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field("minioadmin", alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field("minioadmin", alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(False, alias="MINIO_SECURE")
    minio_bucket_uploads: str = Field("mkb-uploads", alias="MINIO_BUCKET_UPLOADS")
    minio_bucket_exports: str = Field("mkb-exports", alias="MINIO_BUCKET_EXPORTS")
    exports_presign_expire_seconds: int = Field(
        3600, alias="EXPORTS_PRESIGN_EXPIRE_SECONDS"
    )

    mcp_enabled: bool = Field(False, alias="MCP_ENABLED")
    mcp_confirmation_required: bool = Field(True, alias="MCP_CONFIRMATION_REQUIRED")
    mcp_streamable_http: bool = Field(False, alias="MCP_STREAMABLE_HTTP")
    mcp_http_timeout_seconds: int = Field(30, alias="MCP_HTTP_TIMEOUT_SECONDS")
    mcp_stdio_timeout_seconds: int = Field(10, alias="MCP_STDIO_TIMEOUT_SECONDS")

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
    retrieval_default_top_k: int = Field(5, alias="RETRIEVAL_DEFAULT_TOP_K")
    retrieval_max_top_k: int = Field(20, alias="RETRIEVAL_MAX_TOP_K")
    retrieval_cache_ttl_seconds: int = Field(300, alias="RETRIEVAL_CACHE_TTL_SECONDS")
    retrieval_cache_enabled: bool = Field(True, alias="RETRIEVAL_CACHE_ENABLED")
    retrieval_min_score: float | None = Field(None, alias="RETRIEVAL_MIN_SCORE")
    retrieval_query_lowercase: bool = Field(False, alias="RETRIEVAL_QUERY_LOWERCASE")
    retrieval_hybrid_enabled: bool = Field(True, alias="RETRIEVAL_HYBRID_ENABLED")
    retrieval_hybrid_ranker: str = Field("rrf", alias="RETRIEVAL_HYBRID_RANKER")
    retrieval_hybrid_dense_weight: float = Field(
        0.7, alias="RETRIEVAL_HYBRID_DENSE_WEIGHT"
    )
    retrieval_hybrid_sparse_weight: float = Field(
        0.3, alias="RETRIEVAL_HYBRID_SPARSE_WEIGHT"
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
    kb_chat_total_timeout_seconds: float = Field(
        45.0, alias="KB_CHAT_TOTAL_TIMEOUT_SECONDS"
    )
    kb_chat_max_total_rounds: int = Field(3, alias="KB_CHAT_MAX_TOTAL_ROUNDS")
    kb_chat_max_retrieval_retries: int = Field(2, alias="KB_CHAT_MAX_RETRIEVAL_RETRIES")
    kb_chat_max_generation_retries: int = Field(
        1, alias="KB_CHAT_MAX_GENERATION_RETRIES"
    )
    kb_chat_force_retrieve: bool = Field(True, alias="KB_CHAT_FORCE_RETRIEVE")
    kb_chat_grader_fail_policy: str = Field(
        "closed", alias="KB_CHAT_GRADER_FAIL_POLICY"
    )
    kb_chat_json_safe_policy: str = Field("stringify", alias="KB_CHAT_JSON_SAFE_POLICY")

    kb_chat_ambiguity_check_enabled: bool = Field(
        True, alias="KB_CHAT_AMBIGUITY_CHECK_ENABLED"
    )
    kb_chat_decomposition_enabled: bool = Field(
        False, alias="KB_CHAT_DECOMPOSITION_ENABLED"
    )
    kb_chat_decomposition_max_sub_questions: int = Field(
        4, alias="KB_CHAT_DECOMPOSITION_MAX_SUB_QUESTIONS"
    )
    kb_chat_multi_query_enabled: bool = Field(
        False, alias="KB_CHAT_MULTI_QUERY_ENABLED"
    )
    kb_chat_multi_query_max_variants: int = Field(
        4, alias="KB_CHAT_MULTI_QUERY_MAX_VARIANTS"
    )
    kb_chat_hyde_enabled: bool = Field(False, alias="KB_CHAT_HYDE_ENABLED")

    kb_chat_trace_enabled: bool = Field(True, alias="KB_CHAT_TRACE_ENABLED")

    # 对话摘要配置
    summary_enabled: bool = Field(False, alias="SUMMARY_ENABLED")
    summary_trigger_min_messages: int = Field(12, alias="SUMMARY_TRIGGER_MIN_MESSAGES")
    summary_trigger_min_tokens: int = Field(800, alias="SUMMARY_TRIGGER_MIN_TOKENS")
    summary_max_tokens: int = Field(256, alias="SUMMARY_MAX_TOKENS")

    ingestion_contextual_enabled: bool = Field(
        True, alias="INGESTION_CONTEXTUAL_ENABLED"
    )
    ingestion_contextual_timeout_seconds: int = Field(
        15, alias="INGESTION_CONTEXTUAL_TIMEOUT_SECONDS"
    )
    ingestion_contextual_max_tokens: int = Field(
        128, alias="INGESTION_CONTEXTUAL_MAX_TOKENS"
    )
    ingestion_contextual_concurrency: int = Field(
        3, alias="INGESTION_CONTEXTUAL_CONCURRENCY"
    )
    ingestion_embedding_batch_size: int = Field(
        32, alias="INGESTION_EMBEDDING_BATCH_SIZE"
    )

    # 导入：URL 抓取/正文抽取配置（最小安全基线）
    ingestion_url_max_redirects: int = Field(3, alias="INGESTION_URL_MAX_REDIRECTS")
    ingestion_url_max_bytes: int = Field(
        20 * 1024 * 1024, alias="INGESTION_URL_MAX_BYTES"
    )
    ingestion_url_user_agent: str = Field(
        "multi-kb-agent/ingestion", alias="INGESTION_URL_USER_AGENT"
    )

    # PDF 解析（MinerU）
    mineru_model_source: str | None = Field(None, alias="MINERU_MODEL_SOURCE")

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

    @field_validator("app_cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> list[str]:
        if v is None:
            return ["http://localhost:5173", "http://127.0.0.1:5173"]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
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
                        return [str(x).strip() for x in parsed if str(x).strip()]
            parts = [p.strip().strip('"').strip("'") for p in raw.split(",")]
            return [p for p in parts if p]
        return [str(v)]

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _is_dev_env(app_env: str) -> bool:
    return app_env.strip().lower() in {"dev", "development", "local", "test"}


def validate_startup_settings(settings: Settings) -> None:
    """启动期安全校验：避免危险默认配置进入非开发环境。"""
    if _is_dev_env(settings.app_env):
        return

    problems: list[str] = []

    llm_key = settings.llm_api_key.strip()
    if not llm_key or llm_key == "REPLACE_ME":
        problems.append("LLM_API_KEY 为空或为占位值（REPLACE_ME）")

    embedding_key = settings.embedding_api_key.strip()
    if not embedding_key or embedding_key == "REPLACE_ME":
        problems.append("EMBEDDING_API_KEY 为空或为占位值（REPLACE_ME）")

    if settings.mcp_enabled and not settings.mcp_confirmation_required:
        problems.append("启用 MCP 时必须开启人工确认（MCP_CONFIRMATION_REQUIRED=true）")

    if problems:
        raise RuntimeError(
            f"启动安全校验失败（APP_ENV={settings.app_env}）：{'; '.join(problems)}"
        )
