"""LangGraph 存储管理器（单例）。

用于托管跨会话记忆（如用户偏好、最近问答等），
后端类型由现有 MEMORY_* 配置控制。
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
    # AsyncPostgresStore 需要 psycopg 风格的连接串。
    return url.replace("postgresql+asyncpg://", "postgresql://")


class StoreManager:
    """LangGraph BaseStore 管理器（单例）。"""

    _store: BaseStore | None = None
    _store_ctx: AbstractAsyncContextManager[BaseStore] | None = None
    _initialized: bool = False

    @classmethod
    async def initialize(cls) -> None:
        """初始化存储管理器（应用启动时调用）。"""
        if cls._initialized:
            return

        settings = get_settings()
        backend = (settings.memory_store_backend or "").strip().lower() or "postgres"

        # 记忆能力是可选项；禁用时仍保留内存版 store，
        # 以便下游代码安全运行，但读写仍应受 settings.memory_enabled 约束。
        if not settings.memory_enabled or backend == "memory":
            cls._store = InMemoryStore()
            cls._initialized = True
            return

        if backend != "postgres":
            raise ValueError(f"不支持的记忆后端类型: {settings.memory_store_backend}")

        try:
            store_ctx = AsyncPostgresStore.from_conn_string(
                _resolve_store_url(settings)
            )
            cls._store_ctx = store_ctx
            cls._store = await store_ctx.__aenter__()
            await cls._store.setup()
            cls._initialized = True
        except Exception:
            # 记忆能力属于非关键可选组件；初始化失败时降级为内存 store。
            logger.exception("初始化 LangGraph Store 失败，已降级为 InMemoryStore。")
            cls._store = InMemoryStore()
            cls._store_ctx = None
            cls._initialized = True

    @classmethod
    async def shutdown(cls) -> None:
        """关闭存储管理器（应用关闭时调用）。"""
        if cls._store_ctx is not None:
            await cls._store_ctx.__aexit__(None, None, None)
        cls._store = None
        cls._store_ctx = None
        cls._initialized = False

    @classmethod
    def get_store(cls) -> BaseStore:
        """获取存储实例。"""
        if not cls._initialized or cls._store is None:
            raise RuntimeError("StoreManager 未初始化")
        return cls._store
