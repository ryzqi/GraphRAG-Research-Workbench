"""LangGraph 检查点管理器。

提供 AsyncPostgresSaver 的统一管理，支持检查点持久化和恢复。
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.settings import get_settings


class CheckpointManager:
    """检查点管理器（单例）。"""

    _checkpointer: AsyncPostgresSaver | None = None
    _checkpointer_ctx: AbstractAsyncContextManager[AsyncPostgresSaver] | None = None
    _initialized: bool = False

    @classmethod
    async def initialize(cls) -> None:
        """初始化检查点管理器（应用启动时调用）。"""
        if cls._initialized:
            return

        settings = get_settings()
        # 转换 asyncpg URL 为 psycopg 格式
        db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

        checkpointer_ctx = AsyncPostgresSaver.from_conn_string(db_url)
        cls._checkpointer_ctx = checkpointer_ctx
        cls._checkpointer = await checkpointer_ctx.__aenter__()
        await cls._checkpointer.setup()
        cls._initialized = True

    @classmethod
    async def shutdown(cls) -> None:
        """关闭检查点管理器（应用关闭时调用）。"""
        if cls._checkpointer_ctx is not None:
            await cls._checkpointer_ctx.__aexit__(None, None, None)
        cls._checkpointer_ctx = None
        cls._checkpointer = None
        cls._initialized = False

    @classmethod
    def get_checkpointer(cls) -> AsyncPostgresSaver:
        """获取检查点实例。"""
        if not cls._initialized or cls._checkpointer is None:
            raise RuntimeError("CheckpointManager 未初始化")
        return cls._checkpointer

    @classmethod
    def make_config(cls, thread_id: str) -> dict[str, Any]:
        """创建运行配置。"""
        return {"configurable": {"thread_id": thread_id}}

    @classmethod
    async def get_state(cls, thread_id: str) -> Any | None:
        """获取线程的最新检查点状态。"""
        config = cls.make_config(thread_id)
        return await cls.get_checkpointer().aget_tuple(config)

    @classmethod
    async def list_history(cls, thread_id: str, limit: int = 10) -> list[Any]:
        """列出线程的检查点历史。"""
        config = cls.make_config(thread_id)
        history = []
        async for checkpoint in cls.get_checkpointer().alist(config, limit=limit):
            history.append(checkpoint)
        return history

    @classmethod
    async def delete_thread(cls, thread_id: str) -> None:
        """删除线程的所有检查点。"""
        await cls.get_checkpointer().adelete_thread(thread_id)
