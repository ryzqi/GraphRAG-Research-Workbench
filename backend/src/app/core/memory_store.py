"""LangGraph store manager (singleton).

We use LangGraph Store for cross-session memory (user preferences, recent Q/A, etc.).
The store backend is controlled by existing MEMORY_* settings.
"""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import AsyncPostgresStore

from app.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def _resolve_store_url(settings: Settings) -> str:
    url = settings.memory_store_url or settings.database_url
    # AsyncPostgresStore uses psycopg style URLs.
    return url.replace("postgresql+asyncpg://", "postgresql://")


class StoreManager:
    """Store manager (singleton) for LangGraph BaseStore."""

    _store: BaseStore | None = None
    _store_ctx: AbstractAsyncContextManager[BaseStore] | None = None
    _initialized: bool = False

    @classmethod
    async def initialize(cls) -> None:
        """Initialize store manager (called at app startup)."""
        if cls._initialized:
            return

        settings = get_settings()
        backend = (settings.memory_store_backend or "").strip().lower() or "postgres"

        # MEMORY is optional; when disabled, keep an in-memory store instance so downstream code
        # can still compile safely (but should gate on settings.memory_enabled for reads/writes).
        if not settings.memory_enabled or backend == "memory":
            cls._store = InMemoryStore()
            cls._initialized = True
            return

        if backend != "postgres":
            raise ValueError(f"不支持的记忆后端类型: {settings.memory_store_backend}")

        try:
            store_ctx = AsyncPostgresStore.from_conn_string(_resolve_store_url(settings))
            cls._store_ctx = store_ctx
            cls._store = await store_ctx.__aenter__()
            await cls._store.setup()
            cls._initialized = True
        except Exception:
            # Memory is a non-critical optional component; fall back to in-memory store.
            logger.exception("初始化 LangGraph Store 失败，已降级为 InMemoryStore。")
            cls._store = InMemoryStore()
            cls._store_ctx = None
            cls._initialized = True

    @classmethod
    async def shutdown(cls) -> None:
        """Shutdown store manager (called at app shutdown)."""
        if cls._store_ctx is not None:
            await cls._store_ctx.__aexit__(None, None, None)
        cls._store = None
        cls._store_ctx = None
        cls._initialized = False

    @classmethod
    def get_store(cls) -> BaseStore:
        """Get the store instance."""
        if not cls._initialized or cls._store is None:
            raise RuntimeError("StoreManager 未初始化")
        return cls._store

