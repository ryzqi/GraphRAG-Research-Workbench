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
    )

    app_name: str = "多知识库知识代理"
    app_log_level: str = Field("INFO", alias="APP_LOG_LEVEL")
    app_cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        alias="APP_CORS_ALLOW_ORIGINS",
    )

    database_url: str = Field(
        "postgresql+asyncpg://mkb:mkb_password@localhost:5432/mkb",
        alias="DATABASE_URL",
    )
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field("redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field("redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")

    milvus_host: str = Field("localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(19530, alias="MILVUS_PORT")
    milvus_collection: str = Field("kb_chunks_v1", alias="MILVUS_COLLECTION")

    llm_base_url: str = Field("https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field("REPLACE_ME", alias="LLM_API_KEY")
    llm_model: str = Field("gpt-4o-mini", alias="LLM_MODEL")

    embedding_base_url: str = Field("https://api.openai.com/v1", alias="EMBEDDING_BASE_URL")
    embedding_api_key: str = Field("REPLACE_ME", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
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

    # 检索配置
    retrieval_default_top_k: int = Field(5, alias="RETRIEVAL_DEFAULT_TOP_K")
    retrieval_max_top_k: int = Field(20, alias="RETRIEVAL_MAX_TOP_K")
    retrieval_cache_ttl_seconds: int = Field(300, alias="RETRIEVAL_CACHE_TTL_SECONDS")
    retrieval_cache_enabled: bool = Field(True, alias="RETRIEVAL_CACHE_ENABLED")

    # JWT 认证配置
    jwt_secret_key: str = Field("CHANGE_ME_IN_PRODUCTION", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", alias="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(60 * 24, alias="JWT_EXPIRE_MINUTES")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
