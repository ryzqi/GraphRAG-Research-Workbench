"""LangGraph 存储管理器（单例）。

用于托管跨会话记忆（如用户偏好、最近问答等），
后端类型由现有 MEMORY_* 配置控制。
"""

from __future__ import annotations

import logging

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import AsyncPostgresStore

from app.core.settings import get_settings
from app.integrations.langgraph_postgres_pool import LangGraphPostgresPool

logger = logging.getLogger(__name__)


class StoreManager:
    """LangGraph BaseStore 管理器（单例）。"""

    _store: BaseStore | None = None
    _initialized: bool = False
    _enabled: bool = False
    _configured_backend: str = "postgres"
    _effective_backend: str = "memory"
    _degraded_reason: str | None = None

    @classmethod
    async def initialize(cls) -> None:
        """初始化存储管理器（应用启动时调用）。"""
        if cls._initialized:
            return

        settings = get_settings()
        backend = (settings.memory_store_backend or "").strip().lower() or "postgres"
        cls._enabled = bool(settings.memory_enabled)
        cls._configured_backend = backend
        cls._effective_backend = "memory"
        cls._degraded_reason = None

        # 记忆能力是可选项；禁用时仍保留内存版 store，
        # 以便下游代码安全运行，但读写仍应受 settings.memory_enabled 约束。
        if not settings.memory_enabled or backend == "memory":
            cls._store = InMemoryStore()
            cls._effective_backend = "memory"
            cls._initialized = True
            return

        if backend != "postgres":
            raise ValueError(f"不支持的记忆后端类型: {settings.memory_store_backend}")

        try:
            if not LangGraphPostgresPool._initialized:
                raise RuntimeError("LangGraphPostgresPool 未初始化")
            cls._store = AsyncPostgresStore(conn=LangGraphPostgresPool.get_pool())
            await cls._store.setup()
            cls._effective_backend = "postgres"
            cls._initialized = True
        except Exception:
            # 记忆能力属于非关键可选组件；初始化失败时降级为内存 store。
            logger.exception("初始化 LangGraph Store 失败，已降级为 InMemoryStore。")
            cls._store = InMemoryStore()
            cls._effective_backend = "memory"
            cls._degraded_reason = "persistent_store_unavailable"
            cls._initialized = True

    @classmethod
    async def shutdown(cls) -> None:
        """关闭存储管理器（应用关闭时调用）。"""
        cls._store = None
        cls._initialized = False
        cls._enabled = False
        cls._configured_backend = "postgres"
        cls._effective_backend = "memory"
        cls._degraded_reason = None

    @classmethod
    def get_store(cls) -> BaseStore:
        """获取存储实例。"""
        if not cls._initialized or cls._store is None:
            raise RuntimeError("StoreManager 未初始化")
        return cls._store

    @classmethod
    def status(cls) -> dict[str, object]:
        degraded = bool(cls._enabled and cls._configured_backend != cls._effective_backend)
        if not cls._enabled:
            status = "disabled"
        elif degraded:
            status = "degraded"
        elif cls._initialized and cls._store is not None:
            status = "ready"
        else:
            status = "error"
        return {
            "status": status,
            "enabled": cls._enabled,
            "initialized": cls._initialized,
            "configured_backend": cls._configured_backend,
            "effective_backend": cls._effective_backend,
            "degraded": degraded,
            "reason": cls._degraded_reason,
        }
