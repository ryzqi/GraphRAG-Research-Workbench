"""DeepAgents store manager (singleton)."""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore

from app.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def _resolve_store_url(settings: Settings) -> str:
    url = settings.memory_store_url or settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql://")


class DeepAgentsStoreManager:
    """Store manager (singleton) for DeepAgents BaseStore."""

    _store: BaseStore | None = None
    _store_ctx: AbstractContextManager[BaseStore] | None = None
    _initialized: bool = False

    @classmethod
    def initialize(cls) -> None:
        """Initialize DeepAgents store manager (called at app startup)."""
        if cls._initialized:
            return

        settings = get_settings()
        backend = (settings.memory_store_backend or "").strip().lower()

        if not settings.memory_enabled or backend == "memory":
            cls._store = InMemoryStore()
            cls._initialized = True
            return

        if backend != "postgres":
            raise ValueError(f"不支持的记忆后端类型: {settings.memory_store_backend}")

        try:
            store_ctx = PostgresStore.from_conn_string(_resolve_store_url(settings))
            cls._store_ctx = store_ctx
            cls._store = store_ctx.__enter__()
            cls._store.setup()
            cls._initialized = True
        except Exception:
            logger.exception("初始化 DeepAgents Store 失败，已降级为 InMemoryStore。")
            cls._store = InMemoryStore()
            cls._store_ctx = None
            cls._initialized = True

    @classmethod
    def shutdown(cls) -> None:
        """Shutdown DeepAgents store manager (called at app shutdown)."""
        if cls._store_ctx is not None:
            cls._store_ctx.__exit__(None, None, None)
        cls._store = None
        cls._store_ctx = None
        cls._initialized = False

    @classmethod
    def get_store(cls) -> BaseStore:
        """Get initialized DeepAgents store instance."""
        if not cls._initialized or cls._store is None:
            raise RuntimeError("DeepAgentsStoreManager 未初始化")
        return cls._store
