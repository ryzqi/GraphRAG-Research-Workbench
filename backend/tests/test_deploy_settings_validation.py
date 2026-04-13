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

    settings = DeploySettings(_env_file=None)

    assert settings.app_env is AppEnv.PROD
    assert settings.core.app_env is AppEnv.PROD
    assert settings.core.app_log_level == "DEBUG"
    assert settings.core.database_url == settings.database_url
    assert settings.storage.minio_endpoint == "minio.internal:9000"
    assert settings.web_search_provider.searxng_search_base_url == "https://searx.internal"
    assert settings.research_gate.min_quality_score == pytest.approx(0.9)


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
    )

    assert settings.app_env is AppEnv.TEST
    assert settings.core.app_env is AppEnv.TEST
    assert settings.core.database_url == settings.database_url
    assert settings.storage.minio_access_key == settings.minio_access_key
    assert settings.web_search_provider.searxng_search_base_url == (
        settings.searxng_search_base_url
    )


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
