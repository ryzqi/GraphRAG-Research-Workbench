from __future__ import annotations

from urllib.parse import urlsplit

from app.core.settings import Settings


def test_settings_normalizes_localhost_urls_on_windows(monkeypatch) -> None:
    import app.core.settings as settings_module

    monkeypatch.setattr(settings_module.sys, "platform", "win32", raising=False)

    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5433/db",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/0",
        celery_result_backend="redis://localhost:6379/1",
        minio_endpoint="localhost:9000",
        milvus_host="localhost",
        _env_file=None,
    )

    assert urlsplit(settings.database_url).hostname == "127.0.0.1"
    assert urlsplit(settings.redis_url).hostname == "127.0.0.1"
    assert urlsplit(settings.celery_broker_url).hostname == "127.0.0.1"
    assert urlsplit(settings.celery_result_backend).hostname == "127.0.0.1"
    assert settings.minio_endpoint.startswith("127.0.0.1:")
    assert settings.milvus_host == "127.0.0.1"


def test_settings_keeps_localhost_urls_on_non_windows(monkeypatch) -> None:
    import app.core.settings as settings_module

    monkeypatch.setattr(settings_module.sys, "platform", "linux", raising=False)

    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5433/db",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/0",
        celery_result_backend="redis://localhost:6379/1",
        minio_endpoint="localhost:9000",
        milvus_host="localhost",
        _env_file=None,
    )

    assert urlsplit(settings.database_url).hostname == "localhost"
    assert urlsplit(settings.redis_url).hostname == "localhost"
    assert urlsplit(settings.celery_broker_url).hostname == "localhost"
    assert urlsplit(settings.celery_result_backend).hostname == "localhost"
    assert settings.minio_endpoint == "localhost:9000"
    assert settings.milvus_host == "localhost"


def test_settings_includes_only_nextjs_dev_origins_in_dev_mode() -> None:
    settings = Settings(
        app_env="dev",
        app_cors_allow_origins='["http://localhost:5173", "http://127.0.0.1:5173", "https://dev.example.com"]',
        _env_file=None,
    )

    assert "http://localhost:3000" in settings.app_cors_allow_origins
    assert "http://127.0.0.1:3000" in settings.app_cors_allow_origins
    assert "http://localhost:5173" not in settings.app_cors_allow_origins
    assert "http://127.0.0.1:5173" not in settings.app_cors_allow_origins
    assert "https://dev.example.com" in settings.app_cors_allow_origins


def test_settings_preserves_custom_cors_origins_in_non_dev_mode() -> None:
    settings = Settings(
        app_env="prod",
        app_cors_allow_origins='["https://app.example.com"]',
        _env_file=None,
    )

    assert settings.app_cors_allow_origins == ["https://app.example.com"]
