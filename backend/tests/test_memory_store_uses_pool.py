from unittest.mock import MagicMock

import pytest

from app.core import memory_store as ms_module


@pytest.fixture(autouse=True)
def _reset() -> None:
    ms_module.StoreManager._store = None
    ms_module.StoreManager._initialized = False
    ms_module.StoreManager._enabled = False
    ms_module.StoreManager._configured_backend = "postgres"
    ms_module.StoreManager._effective_backend = "memory"
    ms_module.StoreManager._degraded_reason = None
    if hasattr(ms_module.StoreManager, "_store_ctx"):
        ms_module.StoreManager._store_ctx = None
    yield
    ms_module.StoreManager._store = None
    ms_module.StoreManager._initialized = False
    ms_module.StoreManager._enabled = False
    ms_module.StoreManager._configured_backend = "postgres"
    ms_module.StoreManager._effective_backend = "memory"
    ms_module.StoreManager._degraded_reason = None
    if hasattr(ms_module.StoreManager, "_store_ctx"):
        ms_module.StoreManager._store_ctx = None


async def test_initialize_uses_pool_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pool = MagicMock(name="pool")
    monkeypatch.setattr(
        ms_module.LangGraphPostgresPool,
        "get_pool",
        classmethod(lambda cls: fake_pool),
    )
    monkeypatch.setattr(
        ms_module.LangGraphPostgresPool,
        "_initialized",
        True,
    )

    class _Store:
        def __init__(self, conn: object) -> None:
            self.conn = conn

        async def setup(self) -> None:
            return None

    monkeypatch.setattr(ms_module, "AsyncPostgresStore", _Store)

    class _FakeSettings:
        memory_enabled = True
        memory_store_backend = "postgres"
        memory_store_url = None
        database_url = "postgresql+asyncpg://x"

    monkeypatch.setattr(ms_module, "get_settings", lambda: _FakeSettings())

    await ms_module.StoreManager.initialize()
    store = ms_module.StoreManager.get_store()

    assert store.conn is fake_pool


async def test_initialize_falls_back_to_memory_when_pool_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ms_module.LangGraphPostgresPool,
        "_initialized",
        False,
    )

    class _FakeSettings:
        memory_enabled = True
        memory_store_backend = "postgres"
        memory_store_url = None
        database_url = "postgresql+asyncpg://x"

    monkeypatch.setattr(ms_module, "get_settings", lambda: _FakeSettings())

    await ms_module.StoreManager.initialize()

    assert ms_module.StoreManager._effective_backend == "memory"
    assert ms_module.StoreManager._degraded_reason == "persistent_store_unavailable"
