"""DeepAgents 存储管理器（单例）。"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from app.core.memory_store import StoreManager
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class DeepAgentsStoreManager:
    """DeepAgents BaseStore 管理器（单例）。"""

    _store: BaseStore | None = None
    _store_ctx: AbstractContextManager[BaseStore] | None = None
    _initialized: bool = False

    @classmethod
    def initialize(cls) -> None:
        """初始化 DeepAgents Store 管理器（应用启动时调用）。"""
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
            # 直接复用已初始化的异步 LangGraph Store，
            # 避免应用启动时再次同步初始化 PostgresStore。
            cls._store = StoreManager.get_store()
            cls._store_ctx = None
            cls._initialized = True
        except Exception:
            logger.exception("复用 LangGraph Store 初始化 DeepAgents Store 失败，已降级为 InMemoryStore。")
            cls._store = InMemoryStore()
            cls._store_ctx = None
            cls._initialized = True

    @classmethod
    def shutdown(cls) -> None:
        """关闭 DeepAgents Store 管理器（应用关闭时调用）。"""
        if cls._store_ctx is not None:
            cls._store_ctx.__exit__(None, None, None)
        cls._store = None
        cls._store_ctx = None
        cls._initialized = False

    @classmethod
    def get_store(cls) -> BaseStore:
        """获取已初始化的 DeepAgents Store 实例。"""
        if not cls._initialized or cls._store is None:
            raise RuntimeError("DeepAgentsStoreManager 未初始化")
        return cls._store
