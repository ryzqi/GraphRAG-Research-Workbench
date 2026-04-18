import pytest
from psycopg.rows import dict_row

from app.core.settings import Settings
from app.integrations import langgraph_postgres_pool as pool_module


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _reset_pool() -> None:
    pool_module.LangGraphPostgresPool._pool = None
    pool_module.LangGraphPostgresPool._initialized = False
    pool_module.LangGraphPostgresPool._conn_string = None
    yield
    pool_module.LangGraphPostgresPool._pool = None
    pool_module.LangGraphPostgresPool._initialized = False
    pool_module.LangGraphPostgresPool._conn_string = None


async def test_pool_uses_psycopg_connection_string(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _PoolCls:
        def __init__(self, conn_string: str, **kwargs: object) -> None:
            captured["conn_string"] = conn_string
            captured["kwargs"] = kwargs

        async def open(self) -> None:
            captured["opened"] = True

        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(pool_module, "AsyncConnectionPool", _PoolCls)

    settings = _make_settings(
        database_url="postgresql+asyncpg://user:pw@host/db",
        langgraph_postgres_pool_min_size=3,
        langgraph_postgres_pool_max_size=8,
        langgraph_postgres_pool_timeout_seconds=20.0,
    )

    await pool_module.LangGraphPostgresPool.initialize(settings)

    assert captured["conn_string"] == "postgresql://user:pw@host/db"
    assert captured["kwargs"]["min_size"] == 3
    assert captured["kwargs"]["max_size"] == 8
    assert captured["kwargs"]["timeout"] == 20.0
    assert captured["kwargs"]["open"] is False
    assert captured["kwargs"]["kwargs"] == {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }
    assert captured["opened"] is True
    assert pool_module.LangGraphPostgresPool.get_pool() is not None


async def test_get_pool_before_initialize_raises() -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        pool_module.LangGraphPostgresPool.get_pool()


async def test_shutdown_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _PoolCls:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def open(self) -> None:
            calls.append("open")

        async def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(pool_module, "AsyncConnectionPool", _PoolCls)

    await pool_module.LangGraphPostgresPool.initialize(
        _make_settings(database_url="postgresql+asyncpg://user:pw@host/db")
    )
    await pool_module.LangGraphPostgresPool.shutdown()
    await pool_module.LangGraphPostgresPool.shutdown()

    assert calls.count("open") == 1
    assert calls.count("close") == 1
