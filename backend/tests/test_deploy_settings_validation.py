from __future__ import annotations

import pytest

from app.config.app_env import AppEnv
from app.config.deploy_settings import DeploySettings
from app.core.settings import Settings, validate_startup_settings


def test_deploy_settings_supports_legacy_and_nested_env_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.setenv("CORE__APP_ENV", "production")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://svc:strong-password@db.internal:5432/app",
    )
    monkeypatch.setenv("STORAGE__MINIO_ENDPOINT", "minio.internal:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "storage-access-key")
    monkeypatch.setenv("MINIO_SECRET_KEY", "storage-secret-key")
    monkeypatch.setenv("WEB_SEARCH__SEARXNG_SEARCH_BASE_URL", "https://searx.internal")
    monkeypatch.setenv("RESEARCH_GATE__MIN_QUALITY_SCORE", "0.9")
    monkeypatch.setenv("CORE__EMBEDDING_MAX_BATCH_SIZE", "25")

    settings = DeploySettings(_env_file=None)

    assert settings.app_env is AppEnv.PROD
    assert settings.core.app_env is AppEnv.PROD
    assert settings.core.app_log_level == "DEBUG"
    assert settings.core.database_url == settings.database_url
    assert settings.storage.minio_endpoint == "minio.internal:9000"
    assert settings.web_search_provider.searxng_search_base_url == "https://searx.internal"
    assert settings.research_gate.min_quality_score == pytest.approx(0.9)
    assert settings.embedding_max_batch_size == 25
    assert settings.core.embedding_max_batch_size == 25


def test_settings_exposes_typed_deploy_groups_without_breaking_flat_access() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://svc:strong-password@db.internal:5432/app",
        REDIS_URL="redis://cache.internal:6379/0",
        CELERY_BROKER_URL="redis://cache.internal:6379/0",
        CELERY_RESULT_BACKEND="redis://cache.internal:6379/1",
        MINIO_ENDPOINT="minio.internal:9000",
        MINIO_ACCESS_KEY="storage-access-key",
        MINIO_SECRET_KEY="storage-secret-key",
        SEARXNG_BASE_URL="https://searx.internal",
        EMBEDDING_API_KEY="embed-key",
        MODEL_CONFIG_KMS_KEY="kms-key",
        RETRIEVAL_RERANK_MAX_DOCUMENTS_PER_REQUEST=None,
    )

    assert settings.app_env is AppEnv.TEST
    assert settings.core.app_env is AppEnv.TEST
    assert settings.core.database_url == settings.database_url
    assert settings.storage.minio_access_key == settings.minio_access_key
    assert settings.web_search_provider.searxng_search_base_url == (
        settings.searxng_search_base_url
    )
    assert settings.retrieval_rerank_max_documents_per_request is None


def test_settings_preserves_celery_worker_runtime_contract() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://svc:strong-password@db.internal:5432/app",
        REDIS_URL="redis://cache.internal:6379/0",
        CELERY_BROKER_URL="redis://cache.internal:6379/0",
        CELERY_RESULT_BACKEND="redis://cache.internal:6379/1",
        MINIO_ENDPOINT="minio.internal:9000",
        MINIO_ACCESS_KEY="storage-access-key",
        MINIO_SECRET_KEY="storage-secret-key",
        SEARXNG_BASE_URL="https://searx.internal",
        EMBEDDING_API_KEY="embed-key",
        MODEL_CONFIG_KMS_KEY="kms-key",
    )

    assert settings.celery_broker_visibility_timeout_seconds == 7_200
    assert settings.celery_task_store_errors_even_if_ignored is True
    assert settings.celery_worker_send_task_events is False
    assert settings.celery_task_send_sent_event is False
    assert settings.celery_worker_prefetch_multiplier == 1
    assert settings.research_outbox_stale_dispatched_seconds is None

    from app.worker.celery_app import _build_celery_conf

    conf = _build_celery_conf(settings)
    assert conf["broker_transport_options"]["visibility_timeout"] == 7_200
    assert conf["task_store_errors_even_if_ignored"] is True
    assert conf["worker_send_task_events"] is False
    assert conf["task_send_sent_event"] is False
    assert conf["worker_prefetch_multiplier"] == 1


def test_settings_exposes_semantic_cache_recovery_cooldown() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://svc:strong-password@db.internal:5432/app",
        REDIS_URL="redis://cache.internal:6379/0",
        CELERY_BROKER_URL="redis://cache.internal:6379/0",
        CELERY_RESULT_BACKEND="redis://cache.internal:6379/1",
        MINIO_ENDPOINT="minio.internal:9000",
        MINIO_ACCESS_KEY="storage-access-key",
        MINIO_SECRET_KEY="storage-secret-key",
        SEARXNG_BASE_URL="https://searx.internal",
        EMBEDDING_API_KEY="embed-key",
        MODEL_CONFIG_KMS_KEY="kms-key",
        KB_CHAT_SEMANTIC_CACHE_RECOVERY_COOLDOWN_SECONDS=15,
    )

    assert settings.kb_chat_semantic_cache_recovery_cooldown_seconds == 15


def test_validate_startup_settings_rejects_prod_loopback_and_placeholder_values() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="prod",
        DATABASE_URL="postgresql+asyncpg://svc:strong-password@localhost:5432/app",
        REDIS_URL="redis://cache.internal:6379/0",
        CELERY_BROKER_URL="redis://cache.internal:6379/0",
        CELERY_RESULT_BACKEND="redis://cache.internal:6379/1",
        MINIO_ENDPOINT="127.0.0.1:9000",
        MINIO_ACCESS_KEY="minioadmin",
        MINIO_SECRET_KEY="minioadmin",
        SEARXNG_BASE_URL="http://127.0.0.1:18080",
        EMBEDDING_API_KEY="REPLACE_ME",
        MODEL_CONFIG_KMS_KEY="",
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_startup_settings(settings)

    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "MINIO_ENDPOINT" in message
    assert "MINIO_ACCESS_KEY" in message
    assert "MINIO_SECRET_KEY" in message
    assert "SEARXNG_BASE_URL" in message
    assert "EMBEDDING_API_KEY" in message
    assert "MODEL_CONFIG_KMS_KEY" in message


def test_validate_startup_settings_allows_dev_profile_defaults() -> None:
    settings = Settings(_env_file=None)

    validate_startup_settings(settings)
