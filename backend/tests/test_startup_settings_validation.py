from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.settings import (
    _DEFAULT_CELERY_BROKER_URL,
    _DEFAULT_CELERY_RESULT_BACKEND,
    _DEFAULT_DATABASE_URL,
    _DEFAULT_MINIO_ACCESS_KEY,
    _DEFAULT_MINIO_SECRET_KEY,
    _DEFAULT_REDIS_URL,
    validate_startup_settings,
)


def _settings_stub(**overrides: object) -> SimpleNamespace:
    base = {
        "app_env": "dev",
        "llm_api_key": "REPLACE_ME",
        "embedding_api_key": "REPLACE_ME",
        "model_config_kms_key": None,
        "database_url": _DEFAULT_DATABASE_URL,
        "redis_url": _DEFAULT_REDIS_URL,
        "celery_broker_url": _DEFAULT_CELERY_BROKER_URL,
        "celery_result_backend": _DEFAULT_CELERY_RESULT_BACKEND,
        "minio_access_key": _DEFAULT_MINIO_ACCESS_KEY,
        "minio_secret_key": _DEFAULT_MINIO_SECRET_KEY,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_validate_startup_settings_skips_dev_environment() -> None:
    settings = _settings_stub(app_env="dev")
    validate_startup_settings(settings)


def test_validate_startup_settings_rejects_default_infra_credentials_in_non_dev() -> None:
    settings = _settings_stub(
        app_env="prod",
        llm_api_key="test-llm-key",
        embedding_api_key="test-embedding-key",
        model_config_kms_key="test-kms-key",
    )

    with pytest.raises(RuntimeError) as exc:
        validate_startup_settings(settings)

    message = str(exc.value)
    assert "DATABASE_URL 使用默认示例凭据" in message
    assert "REDIS_URL 使用默认示例配置" in message
    assert "CELERY_BROKER_URL 使用默认示例配置" in message
    assert "CELERY_RESULT_BACKEND 使用默认示例配置" in message
    assert "MINIO_ACCESS_KEY 使用默认值" in message
    assert "MINIO_SECRET_KEY 使用默认值" in message


def test_validate_startup_settings_allows_non_default_infra_credentials_in_non_dev() -> None:
    settings = _settings_stub(
        app_env="staging",
        llm_api_key="test-llm-key",
        embedding_api_key="test-embedding-key",
        model_config_kms_key="test-kms-key",
        database_url="postgresql+asyncpg://mkb:strong_pwd@db.example.com:5432/mkb",
        redis_url="redis://redis.example.com:6380/0",
        celery_broker_url="redis://redis.example.com:6380/2",
        celery_result_backend="redis://redis.example.com:6380/3",
        minio_access_key="access-key",
        minio_secret_key="secret-key",
    )

    validate_startup_settings(settings)
