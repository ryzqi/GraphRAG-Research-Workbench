from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from app.config.app_env import AppEnv
from app.config.validators import (
    DEV_DEFAULT_CELERY_BROKER_URL,
    DEV_DEFAULT_CELERY_RESULT_BACKEND,
    DEV_DEFAULT_DATABASE_URL,
    DEV_DEFAULT_MINIO_ACCESS_KEY,
    DEV_DEFAULT_MINIO_SECRET_KEY,
    DEV_DEFAULT_REDIS_URL,
    ensure_local_dev_cors_origins,
    parse_origins,
    parse_string_list,
    prefer_ipv4_loopback_hostport,
    prefer_ipv4_loopback_url,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_SECRETS_DIR = ROOT_DIR / ".secrets"


def _deploy_field(
    default: Any | None = None,
    *,
    default_factory: Any | None = None,
    legacy_alias: str,
    nested_alias: str,
    **kwargs: Any,
) -> Any:
    field_kwargs = {
        "alias": legacy_alias,
        "validation_alias": AliasChoices(legacy_alias, nested_alias),
        **kwargs,
    }
    if default_factory is not None:
        return Field(default_factory=default_factory, **field_kwargs)
    return Field(default, **field_kwargs)


class CoreDeploySettings(BaseModel):
    app_name: str
    app_env: AppEnv
    app_log_level: str
    app_cors_allow_origins: list[str]
    database_url: str
    db_pool_size: int
    db_max_overflow: int
    db_pool_recycle_seconds: int
    langgraph_postgres_pool_min_size: int
    langgraph_postgres_pool_max_size: int
    langgraph_postgres_pool_timeout_seconds: float
    web_search_pipeline_max_concurrency: int
    redis_url: str
    redis_socket_timeout_seconds: float
    redis_socket_connect_timeout_seconds: float
    celery_broker_url: str
    celery_result_backend: str
    celery_broker_visibility_timeout_seconds: int
    research_outbox_stale_dispatched_seconds: int | None
    celery_task_soft_time_limit_seconds: int
    celery_task_time_limit_seconds: int
    celery_task_store_errors_even_if_ignored: bool
    celery_worker_send_task_events: bool
    celery_task_send_sent_event: bool
    celery_worker_prefetch_multiplier: int
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_timeout_seconds: float
    embedding_dim: int | None
    embedding_max_batch_size: int | None
    model_config_kms_key: str | None


class StorageSettings(BaseModel):
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    minio_bucket_uploads: str
    minio_bucket_exports: str
    bootstrap_upload_presign_expire_seconds: int
    bootstrap_queued_timeout_seconds: int
    research_queued_timeout_seconds: int
    exports_presign_expire_seconds: int


class WebSearchProviderSettings(BaseModel):
    tavily_base_url: str
    searxng_search_enabled: bool
    searxng_search_base_url: str
    searxng_default_categories: list[str]
    searxng_default_language: str | None
    searxng_default_engines: list[str]


class ResearchGateSettings(BaseModel):
    min_quality_score: float
    max_p95_ms: int
    max_session_cost_usd: float


class HttpClientSettings(BaseModel):
    timeout_connect_seconds: float
    timeout_read_seconds: float
    timeout_write_seconds: float
    timeout_pool_seconds: float
    max_connections: int
    max_keepalive_connections: int
    keepalive_expiry_seconds: float
    embedding_realtime_timeout_connect_seconds: float | None
    embedding_realtime_timeout_read_seconds: float | None
    embedding_realtime_timeout_write_seconds: float | None
    embedding_realtime_timeout_pool_seconds: float | None
    embedding_batch_timeout_connect_seconds: float | None
    embedding_batch_timeout_read_seconds: float | None
    embedding_batch_timeout_write_seconds: float | None
    embedding_batch_timeout_pool_seconds: float | None


class DeploySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        secrets_dir=str(DEFAULT_SECRETS_DIR) if DEFAULT_SECRETS_DIR.exists() else None,
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    app_name: str = _deploy_field(
        "多知识库知识代理",
        legacy_alias="APP_NAME",
        nested_alias="CORE__APP_NAME",
    )
    app_env: AppEnv = _deploy_field(
        AppEnv.DEV,
        legacy_alias="APP_ENV",
        nested_alias="CORE__APP_ENV",
    )
    app_log_level: str = _deploy_field(
        "INFO",
        legacy_alias="APP_LOG_LEVEL",
        nested_alias="CORE__APP_LOG_LEVEL",
    )
    app_cors_allow_origins: list[str] = _deploy_field(
        default_factory=list,
        legacy_alias="APP_CORS_ALLOW_ORIGINS",
        nested_alias="CORE__APP_CORS_ALLOW_ORIGINS",
    )
    database_url: str = _deploy_field(
        DEV_DEFAULT_DATABASE_URL,
        legacy_alias="DATABASE_URL",
        nested_alias="CORE__DATABASE_URL",
    )
    db_pool_size: int = _deploy_field(
        5,
        legacy_alias="DB_POOL_SIZE",
        nested_alias="CORE__DB_POOL_SIZE",
    )
    db_max_overflow: int = _deploy_field(
        10,
        legacy_alias="DB_MAX_OVERFLOW",
        nested_alias="CORE__DB_MAX_OVERFLOW",
    )
    db_pool_recycle_seconds: int = _deploy_field(
        1800,
        legacy_alias="DB_POOL_RECYCLE_SECONDS",
        nested_alias="CORE__DB_POOL_RECYCLE_SECONDS",
    )
    langgraph_postgres_pool_min_size: int = _deploy_field(
        2,
        ge=1,
        le=32,
        legacy_alias="LANGGRAPH_POSTGRES_POOL_MIN_SIZE",
        nested_alias="CORE__LANGGRAPH_POSTGRES_POOL_MIN_SIZE",
    )
    langgraph_postgres_pool_max_size: int = _deploy_field(
        10,
        ge=1,
        le=64,
        legacy_alias="LANGGRAPH_POSTGRES_POOL_MAX_SIZE",
        nested_alias="CORE__LANGGRAPH_POSTGRES_POOL_MAX_SIZE",
    )
    langgraph_postgres_pool_timeout_seconds: float = _deploy_field(
        30.0,
        ge=0.1,
        le=300.0,
        legacy_alias="LANGGRAPH_POSTGRES_POOL_TIMEOUT_SECONDS",
        nested_alias="CORE__LANGGRAPH_POSTGRES_POOL_TIMEOUT_SECONDS",
    )
    web_search_pipeline_max_concurrency: int = _deploy_field(
        4,
        ge=1,
        le=32,
        legacy_alias="WEB_SEARCH_PIPELINE_MAX_CONCURRENCY",
        nested_alias="CORE__WEB_SEARCH_PIPELINE_MAX_CONCURRENCY",
    )
    redis_url: str = _deploy_field(
        DEV_DEFAULT_REDIS_URL,
        legacy_alias="REDIS_URL",
        nested_alias="CORE__REDIS_URL",
    )
    redis_socket_timeout_seconds: float = _deploy_field(
        1.0,
        legacy_alias="REDIS_SOCKET_TIMEOUT_SECONDS",
        nested_alias="CORE__REDIS_SOCKET_TIMEOUT_SECONDS",
    )
    redis_socket_connect_timeout_seconds: float = _deploy_field(
        1.0,
        legacy_alias="REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
        nested_alias="CORE__REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
    )
    celery_broker_url: str = _deploy_field(
        DEV_DEFAULT_CELERY_BROKER_URL,
        legacy_alias="CELERY_BROKER_URL",
        nested_alias="CORE__CELERY_BROKER_URL",
    )
    celery_result_backend: str = _deploy_field(
        DEV_DEFAULT_CELERY_RESULT_BACKEND,
        legacy_alias="CELERY_RESULT_BACKEND",
        nested_alias="CORE__CELERY_RESULT_BACKEND",
    )
    # Celery Redis transport 默认 visibility_timeout 为 3600 秒。
    # 这里保持 7200 秒，以降低长任务被提前重投的概率。
    celery_broker_visibility_timeout_seconds: int = _deploy_field(
        7_200,
        ge=1,
        legacy_alias="CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS",
        nested_alias="CORE__CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS",
    )
    research_outbox_stale_dispatched_seconds: int | None = _deploy_field(
        None,
        ge=1,
        legacy_alias="RESEARCH_OUTBOX_STALE_DISPATCHED_SECONDS",
        nested_alias="CORE__RESEARCH_OUTBOX_STALE_DISPATCHED_SECONDS",
    )
    celery_task_soft_time_limit_seconds: int = _deploy_field(
        0,
        ge=0,
        legacy_alias="CELERY_TASK_SOFT_TIME_LIMIT_SECONDS",
        nested_alias="CORE__CELERY_TASK_SOFT_TIME_LIMIT_SECONDS",
    )
    celery_task_time_limit_seconds: int = _deploy_field(
        0,
        ge=0,
        legacy_alias="CELERY_TASK_TIME_LIMIT_SECONDS",
        nested_alias="CORE__CELERY_TASK_TIME_LIMIT_SECONDS",
    )
    celery_task_store_errors_even_if_ignored: bool = _deploy_field(
        True,
        legacy_alias="CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED",
        nested_alias="CORE__CELERY_TASK_STORE_ERRORS_EVEN_IF_IGNORED",
    )
    celery_worker_send_task_events: bool = _deploy_field(
        False,
        legacy_alias="CELERY_WORKER_SEND_TASK_EVENTS",
        nested_alias="CORE__CELERY_WORKER_SEND_TASK_EVENTS",
    )
    celery_task_send_sent_event: bool = _deploy_field(
        False,
        legacy_alias="CELERY_TASK_SEND_SENT_EVENT",
        nested_alias="CORE__CELERY_TASK_SEND_SENT_EVENT",
    )
    celery_worker_prefetch_multiplier: int = _deploy_field(
        1,
        ge=1,
        legacy_alias="CELERY_WORKER_PREFETCH_MULTIPLIER",
        nested_alias="CORE__CELERY_WORKER_PREFETCH_MULTIPLIER",
    )
    http_timeout_connect_seconds: float = _deploy_field(
        10.0,
        legacy_alias="HTTP_TIMEOUT_CONNECT_SECONDS",
        nested_alias="HTTP_CLIENT__TIMEOUT_CONNECT_SECONDS",
    )
    http_timeout_read_seconds: float = _deploy_field(
        30.0,
        legacy_alias="HTTP_TIMEOUT_READ_SECONDS",
        nested_alias="HTTP_CLIENT__TIMEOUT_READ_SECONDS",
    )
    http_timeout_write_seconds: float = _deploy_field(
        30.0,
        legacy_alias="HTTP_TIMEOUT_WRITE_SECONDS",
        nested_alias="HTTP_CLIENT__TIMEOUT_WRITE_SECONDS",
    )
    http_timeout_pool_seconds: float = _deploy_field(
        5.0,
        legacy_alias="HTTP_TIMEOUT_POOL_SECONDS",
        nested_alias="HTTP_CLIENT__TIMEOUT_POOL_SECONDS",
    )
    http_max_connections: int = _deploy_field(
        100,
        legacy_alias="HTTP_MAX_CONNECTIONS",
        nested_alias="HTTP_CLIENT__MAX_CONNECTIONS",
    )
    http_max_keepalive_connections: int = _deploy_field(
        20,
        legacy_alias="HTTP_MAX_KEEPALIVE_CONNECTIONS",
        nested_alias="HTTP_CLIENT__MAX_KEEPALIVE_CONNECTIONS",
    )
    http_keepalive_expiry_seconds: float = _deploy_field(
        5.0,
        legacy_alias="HTTP_KEEPALIVE_EXPIRY_SECONDS",
        nested_alias="HTTP_CLIENT__KEEPALIVE_EXPIRY_SECONDS",
    )
    embedding_http_realtime_timeout_connect_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_REALTIME_TIMEOUT_CONNECT_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_REALTIME_TIMEOUT_CONNECT_SECONDS",
    )
    embedding_http_realtime_timeout_read_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_REALTIME_TIMEOUT_READ_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_REALTIME_TIMEOUT_READ_SECONDS",
    )
    embedding_http_realtime_timeout_write_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_REALTIME_TIMEOUT_WRITE_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_REALTIME_TIMEOUT_WRITE_SECONDS",
    )
    embedding_http_realtime_timeout_pool_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_REALTIME_TIMEOUT_POOL_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_REALTIME_TIMEOUT_POOL_SECONDS",
    )
    embedding_http_batch_timeout_connect_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_BATCH_TIMEOUT_CONNECT_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_BATCH_TIMEOUT_CONNECT_SECONDS",
    )
    embedding_http_batch_timeout_read_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_BATCH_TIMEOUT_READ_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_BATCH_TIMEOUT_READ_SECONDS",
    )
    embedding_http_batch_timeout_write_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_BATCH_TIMEOUT_WRITE_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_BATCH_TIMEOUT_WRITE_SECONDS",
    )
    embedding_http_batch_timeout_pool_seconds: float | None = _deploy_field(
        None,
        ge=0.0,
        legacy_alias="EMBEDDING_HTTP_BATCH_TIMEOUT_POOL_SECONDS",
        nested_alias="HTTP_CLIENT__EMBEDDING_BATCH_TIMEOUT_POOL_SECONDS",
    )
    embedding_base_url: str = _deploy_field(
        "https://api.openai.com/v1",
        legacy_alias="EMBEDDING_BASE_URL",
        nested_alias="CORE__EMBEDDING_BASE_URL",
    )
    embedding_api_key: str = _deploy_field(
        "REPLACE_ME",
        legacy_alias="EMBEDDING_API_KEY",
        nested_alias="CORE__EMBEDDING_API_KEY",
    )
    embedding_model: str = _deploy_field(
        "text-embedding-3-small",
        legacy_alias="EMBEDDING_MODEL",
        nested_alias="CORE__EMBEDDING_MODEL",
    )
    embedding_timeout_seconds: float = _deploy_field(
        30.0,
        legacy_alias="EMBEDDING_TIMEOUT_SECONDS",
        nested_alias="CORE__EMBEDDING_TIMEOUT_SECONDS",
    )
    embedding_dim: int | None = _deploy_field(
        None,
        legacy_alias="EMBEDDING_DIM",
        nested_alias="CORE__EMBEDDING_DIM",
    )
    embedding_max_batch_size: int | None = _deploy_field(
        None,
        ge=1,
        legacy_alias="EMBEDDING_MAX_BATCH_SIZE",
        nested_alias="CORE__EMBEDDING_MAX_BATCH_SIZE",
    )
    model_config_kms_key: str | None = _deploy_field(
        None,
        legacy_alias="MODEL_CONFIG_KMS_KEY",
        nested_alias="CORE__MODEL_CONFIG_KMS_KEY",
    )
    minio_endpoint: str = _deploy_field(
        "localhost:9000",
        legacy_alias="MINIO_ENDPOINT",
        nested_alias="STORAGE__MINIO_ENDPOINT",
    )
    minio_access_key: str = _deploy_field(
        DEV_DEFAULT_MINIO_ACCESS_KEY,
        legacy_alias="MINIO_ACCESS_KEY",
        nested_alias="STORAGE__MINIO_ACCESS_KEY",
    )
    minio_secret_key: str = _deploy_field(
        DEV_DEFAULT_MINIO_SECRET_KEY,
        legacy_alias="MINIO_SECRET_KEY",
        nested_alias="STORAGE__MINIO_SECRET_KEY",
    )
    minio_secure: bool = _deploy_field(
        False,
        legacy_alias="MINIO_SECURE",
        nested_alias="STORAGE__MINIO_SECURE",
    )
    minio_bucket_uploads: str = _deploy_field(
        "mkb-uploads",
        legacy_alias="MINIO_BUCKET_UPLOADS",
        nested_alias="STORAGE__MINIO_BUCKET_UPLOADS",
    )
    minio_bucket_exports: str = _deploy_field(
        "mkb-exports",
        legacy_alias="MINIO_BUCKET_EXPORTS",
        nested_alias="STORAGE__MINIO_BUCKET_EXPORTS",
    )
    bootstrap_upload_presign_expire_seconds: int = _deploy_field(
        900,
        legacy_alias="BOOTSTRAP_UPLOAD_PRESIGN_EXPIRE_SECONDS",
        nested_alias="STORAGE__BOOTSTRAP_UPLOAD_PRESIGN_EXPIRE_SECONDS",
    )
    bootstrap_queued_timeout_seconds: int = _deploy_field(
        180,
        ge=1,
        legacy_alias="BOOTSTRAP_QUEUED_TIMEOUT_SECONDS",
        nested_alias="STORAGE__BOOTSTRAP_QUEUED_TIMEOUT_SECONDS",
    )
    research_queued_timeout_seconds: int = _deploy_field(
        180,
        ge=1,
        legacy_alias="RESEARCH_QUEUED_TIMEOUT_SECONDS",
        nested_alias="STORAGE__RESEARCH_QUEUED_TIMEOUT_SECONDS",
    )
    exports_presign_expire_seconds: int = _deploy_field(
        3600,
        legacy_alias="EXPORTS_PRESIGN_EXPIRE_SECONDS",
        nested_alias="STORAGE__EXPORTS_PRESIGN_EXPIRE_SECONDS",
    )
    searxng_search_enabled: bool = _deploy_field(
        True,
        legacy_alias="SEARXNG_SEARCH_ENABLED",
        nested_alias="WEB_SEARCH__SEARXNG_SEARCH_ENABLED",
    )
    tavily_base_url: str = _deploy_field(
        "https://api.tavily.com",
        legacy_alias="TAVILY_BASE_URL",
        nested_alias="WEB_SEARCH__TAVILY_BASE_URL",
    )
    searxng_search_base_url: str = _deploy_field(
        "http://127.0.0.1:18080",
        legacy_alias="SEARXNG_BASE_URL",
        nested_alias="WEB_SEARCH__SEARXNG_SEARCH_BASE_URL",
    )
    searxng_default_categories: list[str] = _deploy_field(
        default_factory=list,
        legacy_alias="SEARXNG_DEFAULT_CATEGORIES",
        nested_alias="WEB_SEARCH__SEARXNG_DEFAULT_CATEGORIES",
    )
    searxng_default_language: str | None = _deploy_field(
        None,
        legacy_alias="SEARXNG_DEFAULT_LANGUAGE",
        nested_alias="WEB_SEARCH__SEARXNG_DEFAULT_LANGUAGE",
    )
    searxng_default_engines: list[str] = _deploy_field(
        default_factory=list,
        legacy_alias="SEARXNG_DEFAULT_ENGINES",
        nested_alias="WEB_SEARCH__SEARXNG_DEFAULT_ENGINES",
    )
    research_gate_min_quality_score: float = _deploy_field(
        0.75,
        ge=0.0,
        le=1.0,
        legacy_alias="RESEARCH_GATE_MIN_QUALITY_SCORE",
        nested_alias="RESEARCH_GATE__MIN_QUALITY_SCORE",
    )
    research_gate_max_p95_ms: int = _deploy_field(
        180_000,
        ge=1,
        legacy_alias="RESEARCH_GATE_MAX_P95_MS",
        nested_alias="RESEARCH_GATE__MAX_P95_MS",
    )
    research_gate_max_session_cost_usd: float = _deploy_field(
        2.0,
        ge=0.0,
        legacy_alias="RESEARCH_GATE_MAX_SESSION_COST_USD",
        nested_alias="RESEARCH_GATE__MAX_SESSION_COST_USD",
    )

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: object) -> AppEnv:
        return AppEnv.from_value(value)

    @field_validator(
        "database_url",
        "redis_url",
        "celery_broker_url",
        "celery_result_backend",
        "tavily_base_url",
        "searxng_search_base_url",
        mode="before",
    )
    @classmethod
    def _normalize_localhost_urls(cls, value: object) -> object:
        if value is None:
            return value
        return prefer_ipv4_loopback_url(str(value))

    @field_validator("minio_endpoint", mode="before")
    @classmethod
    def _normalize_minio_endpoint(cls, value: object) -> object:
        if value is None:
            return value
        return prefer_ipv4_loopback_hostport(str(value))

    @field_validator("app_cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> list[str]:
        return parse_origins(value)

    @field_validator(
        "searxng_default_categories",
        "searxng_default_engines",
        mode="before",
    )
    @classmethod
    def _parse_searxng_string_lists(cls, value: object) -> list[str]:
        return parse_string_list(value)

    @model_validator(mode="after")
    def _ensure_local_dev_cors_origins(self) -> "DeploySettings":
        self.app_cors_allow_origins = ensure_local_dev_cors_origins(
            self.app_env,
            self.app_cors_allow_origins,
        )
        return self

    @model_validator(mode="after")
    def _validate_celery_time_limit_settings(self) -> "DeploySettings":
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

    @cached_property
    def core(self) -> CoreDeploySettings:
        return CoreDeploySettings(
            app_name=self.app_name,
            app_env=self.app_env,
            app_log_level=self.app_log_level,
            app_cors_allow_origins=self.app_cors_allow_origins,
            database_url=self.database_url,
            db_pool_size=self.db_pool_size,
            db_max_overflow=self.db_max_overflow,
            db_pool_recycle_seconds=self.db_pool_recycle_seconds,
            langgraph_postgres_pool_min_size=self.langgraph_postgres_pool_min_size,
            langgraph_postgres_pool_max_size=self.langgraph_postgres_pool_max_size,
            langgraph_postgres_pool_timeout_seconds=self.langgraph_postgres_pool_timeout_seconds,
            web_search_pipeline_max_concurrency=self.web_search_pipeline_max_concurrency,
            redis_url=self.redis_url,
            redis_socket_timeout_seconds=self.redis_socket_timeout_seconds,
            redis_socket_connect_timeout_seconds=self.redis_socket_connect_timeout_seconds,
            celery_broker_url=self.celery_broker_url,
            celery_result_backend=self.celery_result_backend,
            celery_broker_visibility_timeout_seconds=self.celery_broker_visibility_timeout_seconds,
            research_outbox_stale_dispatched_seconds=self.research_outbox_stale_dispatched_seconds,
            celery_task_soft_time_limit_seconds=self.celery_task_soft_time_limit_seconds,
            celery_task_time_limit_seconds=self.celery_task_time_limit_seconds,
            celery_task_store_errors_even_if_ignored=self.celery_task_store_errors_even_if_ignored,
            celery_worker_send_task_events=self.celery_worker_send_task_events,
            celery_task_send_sent_event=self.celery_task_send_sent_event,
            celery_worker_prefetch_multiplier=self.celery_worker_prefetch_multiplier,
            embedding_base_url=self.embedding_base_url,
            embedding_api_key=self.embedding_api_key,
            embedding_model=self.embedding_model,
            embedding_timeout_seconds=self.embedding_timeout_seconds,
            embedding_dim=self.embedding_dim,
            embedding_max_batch_size=self.embedding_max_batch_size,
            model_config_kms_key=self.model_config_kms_key,
        )

    @cached_property
    def storage(self) -> StorageSettings:
        return StorageSettings(
            minio_endpoint=self.minio_endpoint,
            minio_access_key=self.minio_access_key,
            minio_secret_key=self.minio_secret_key,
            minio_secure=self.minio_secure,
            minio_bucket_uploads=self.minio_bucket_uploads,
            minio_bucket_exports=self.minio_bucket_exports,
            bootstrap_upload_presign_expire_seconds=self.bootstrap_upload_presign_expire_seconds,
            bootstrap_queued_timeout_seconds=self.bootstrap_queued_timeout_seconds,
            research_queued_timeout_seconds=self.research_queued_timeout_seconds,
            exports_presign_expire_seconds=self.exports_presign_expire_seconds,
        )

    @cached_property
    def web_search_provider(self) -> WebSearchProviderSettings:
        return WebSearchProviderSettings(
            tavily_base_url=self.tavily_base_url,
            searxng_search_enabled=self.searxng_search_enabled,
            searxng_search_base_url=self.searxng_search_base_url,
            searxng_default_categories=self.searxng_default_categories,
            searxng_default_language=self.searxng_default_language,
            searxng_default_engines=self.searxng_default_engines,
        )

    @cached_property
    def research_gate(self) -> ResearchGateSettings:
        return ResearchGateSettings(
            min_quality_score=self.research_gate_min_quality_score,
            max_p95_ms=self.research_gate_max_p95_ms,
            max_session_cost_usd=self.research_gate_max_session_cost_usd,
        )

    @cached_property
    def http_client(self) -> HttpClientSettings:
        return HttpClientSettings(
            timeout_connect_seconds=self.http_timeout_connect_seconds,
            timeout_read_seconds=self.http_timeout_read_seconds,
            timeout_write_seconds=self.http_timeout_write_seconds,
            timeout_pool_seconds=self.http_timeout_pool_seconds,
            max_connections=self.http_max_connections,
            max_keepalive_connections=self.http_max_keepalive_connections,
            keepalive_expiry_seconds=self.http_keepalive_expiry_seconds,
            embedding_realtime_timeout_connect_seconds=self.embedding_http_realtime_timeout_connect_seconds,
            embedding_realtime_timeout_read_seconds=self.embedding_http_realtime_timeout_read_seconds,
            embedding_realtime_timeout_write_seconds=self.embedding_http_realtime_timeout_write_seconds,
            embedding_realtime_timeout_pool_seconds=self.embedding_http_realtime_timeout_pool_seconds,
            embedding_batch_timeout_connect_seconds=self.embedding_http_batch_timeout_connect_seconds,
            embedding_batch_timeout_read_seconds=self.embedding_http_batch_timeout_read_seconds,
            embedding_batch_timeout_write_seconds=self.embedding_http_batch_timeout_write_seconds,
            embedding_batch_timeout_pool_seconds=self.embedding_http_batch_timeout_pool_seconds,
        )
