from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[4]
ENV_FILE = ROOT_DIR / ".env"


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
        default_factory=lambda: ["http://localhost:5173"],
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
    celery_broker_url: str = Field("redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field("redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")

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

    embedding_base_url: str = Field("https://api.openai.com/v1", alias="EMBEDDING_BASE_URL")
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
    exports_presign_expire_seconds: int = Field(3600, alias="EXPORTS_PRESIGN_EXPIRE_SECONDS")

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

    # 对话摘要配置
    summary_enabled: bool = Field(False, alias="SUMMARY_ENABLED")
    summary_trigger_min_messages: int = Field(
        12, alias="SUMMARY_TRIGGER_MIN_MESSAGES"
    )
    summary_trigger_min_tokens: int = Field(800, alias="SUMMARY_TRIGGER_MIN_TOKENS")
    summary_max_tokens: int = Field(256, alias="SUMMARY_MAX_TOKENS")

    # 导入切分配置
    ingestion_chunk_size: int = Field(512, alias="INGESTION_CHUNK_SIZE")
    ingestion_chunk_overlap: int = Field(64, alias="INGESTION_CHUNK_OVERLAP")
    ingestion_chunk_strategy: str = Field(
        "sliding_window", alias="INGESTION_CHUNK_STRATEGY"
    )
    ingestion_semantic_min_tokens: int = Field(
        80, alias="INGESTION_SEMANTIC_MIN_TOKENS"
    )
    ingestion_semantic_max_tokens: int = Field(
        256, alias="INGESTION_SEMANTIC_MAX_TOKENS"
    )
    ingestion_semantic_similarity_threshold: float = Field(
        0.6, alias="INGESTION_SEMANTIC_SIMILARITY_THRESHOLD"
    )
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

    # JWT 认证配置
    jwt_secret_key: str = Field("CHANGE_ME_IN_PRODUCTION", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(60 * 24, alias="JWT_EXPIRE_MINUTES")

    # 内部管理接口保护（低成本方案：共享 token）
    admin_token: str = Field("CHANGE_ME_IN_PRODUCTION", alias="ADMIN_TOKEN")

    # OpenTelemetry 配置
    otel_enabled: bool = Field(False, alias="OTEL_ENABLED")
    otel_endpoint: str | None = Field(None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field("multi-kb-agent", alias="OTEL_SERVICE_NAME")

    @field_validator("app_cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> list[str]:
        if v is None:
            return ["http://localhost:5173"]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",")]
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

    jwt_secret = settings.jwt_secret_key.strip()
    if not jwt_secret or jwt_secret == "CHANGE_ME_IN_PRODUCTION" or len(jwt_secret) < 32:
        problems.append("JWT_SECRET_KEY 为空/占位/过短（建议至少 32 字符）")

    llm_key = settings.llm_api_key.strip()
    if not llm_key or llm_key == "REPLACE_ME":
        problems.append("LLM_API_KEY 为空或为占位值（REPLACE_ME）")

    embedding_key = settings.embedding_api_key.strip()
    if not embedding_key or embedding_key == "REPLACE_ME":
        problems.append("EMBEDDING_API_KEY 为空或为占位值（REPLACE_ME）")

    admin_token = settings.admin_token.strip()
    if not admin_token or admin_token == "CHANGE_ME_IN_PRODUCTION" or len(admin_token) < 16:
        problems.append("ADMIN_TOKEN 为空/占位/过短（建议至少 16 字符）")

    if settings.mcp_enabled and not settings.mcp_confirmation_required:
        problems.append("启用 MCP 时必须开启人工确认（MCP_CONFIRMATION_REQUIRED=true）")

    if problems:
        raise RuntimeError(f"启动安全校验失败（APP_ENV={settings.app_env}）：{'; '.join(problems)}")
