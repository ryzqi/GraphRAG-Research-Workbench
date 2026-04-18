import pytest

from app.config.validators import validate_startup_settings
from app.core.settings import Settings


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_langgraph_postgres_pool_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "LANGGRAPH_POSTGRES_POOL_MIN_SIZE",
        "CORE__LANGGRAPH_POSTGRES_POOL_MIN_SIZE",
        "LANGGRAPH_POSTGRES_POOL_MAX_SIZE",
        "CORE__LANGGRAPH_POSTGRES_POOL_MAX_SIZE",
        "LANGGRAPH_POSTGRES_POOL_TIMEOUT_SECONDS",
        "CORE__LANGGRAPH_POSTGRES_POOL_TIMEOUT_SECONDS",
        "WEB_SEARCH_PIPELINE_MAX_CONCURRENCY",
        "CORE__WEB_SEARCH_PIPELINE_MAX_CONCURRENCY",
    ):
        monkeypatch.delenv(env_name, raising=False)

    settings = _make_settings()

    assert settings.langgraph_postgres_pool_min_size == 2
    assert settings.langgraph_postgres_pool_max_size == 10
    assert settings.langgraph_postgres_pool_timeout_seconds == 30.0
    assert settings.web_search_pipeline_max_concurrency == 4
    assert settings.core.langgraph_postgres_pool_min_size == 2
    assert settings.core.langgraph_postgres_pool_max_size == 10
    assert settings.core.langgraph_postgres_pool_timeout_seconds == 30.0
    assert settings.core.web_search_pipeline_max_concurrency == 4


def test_pool_min_must_be_leq_max() -> None:
    settings = _make_settings(
        langgraph_postgres_pool_min_size=20,
        langgraph_postgres_pool_max_size=5,
    )

    with pytest.raises(ValueError, match="must be <="):
        validate_startup_settings(settings)
