from __future__ import annotations

from types import SimpleNamespace

from langgraph.store.memory import InMemoryStore

from app.core import deepagents_store as deepagents_store_module
from app.core import memory_store as memory_store_module


def test_deepagents_store_reuses_existing_store_manager_store_for_postgres_backend(
    monkeypatch,
) -> None:
    fake_store = InMemoryStore()

    monkeypatch.setattr(
        deepagents_store_module,
        "get_settings",
        lambda: SimpleNamespace(
            memory_enabled=True,
            memory_store_backend="postgres",
            memory_store_url="postgresql://example",
            database_url="postgresql+asyncpg://example",
        ),
    )
    monkeypatch.setattr(memory_store_module.StoreManager, "get_store", lambda: fake_store)

    deepagents_store_module.DeepAgentsStoreManager.shutdown()
    deepagents_store_module.DeepAgentsStoreManager.initialize()

    assert deepagents_store_module.DeepAgentsStoreManager.get_store() is fake_store

    deepagents_store_module.DeepAgentsStoreManager.shutdown()
