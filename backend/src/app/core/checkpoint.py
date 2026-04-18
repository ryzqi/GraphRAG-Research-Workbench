"""LangGraph 检查点管理器。"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.integrations.langgraph_postgres_pool import LangGraphPostgresPool


class CheckpointManager:
    """检查点管理器（单例）。"""

    _checkpointer: AsyncPostgresSaver | None = None
    _initialized: bool = False
    _last_error: str | None = None

    @staticmethod
    def _string_key_dict(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items()}

    @classmethod
    async def initialize(cls) -> None:
        """初始化检查点管理器（应用启动时调用）。"""
        if cls._initialized:
            return

        if not LangGraphPostgresPool._initialized:
            raise RuntimeError("CheckpointManager 需要 LangGraph Postgres pool 先初始化")

        cls._checkpointer = AsyncPostgresSaver(conn=LangGraphPostgresPool.get_pool())
        await cls._checkpointer.setup()
        cls._last_error = None
        cls._initialized = True

    @classmethod
    async def shutdown(cls) -> None:
        """关闭检查点管理器（应用关闭时调用）。"""
        cls._checkpointer = None
        cls._initialized = False
        cls._last_error = None

    @classmethod
    def get_checkpointer(cls) -> AsyncPostgresSaver:
        """获取检查点实例。"""
        if not cls._initialized or cls._checkpointer is None:
            raise RuntimeError("CheckpointManager 未初始化")
        return cls._checkpointer

    @classmethod
    def status(cls) -> dict[str, object]:
        ready = cls._initialized and cls._checkpointer is not None
        return {
            "status": "ready" if ready else "error",
            "initialized": cls._initialized,
            "backend": "postgres",
            "reason": cls._last_error,
        }

    @classmethod
    def make_config(cls, thread_id: str) -> RunnableConfig:
        """创建运行配置。"""
        return {"configurable": {"thread_id": thread_id}}

    @classmethod
    async def get_state(cls, thread_id: str) -> Any | None:
        """获取线程的最新检查点状态。"""
        config = cls.make_config(thread_id)
        return await cls.get_checkpointer().aget_tuple(config)

    @staticmethod
    def summarize_channel_values(channel_values: Any) -> dict[str, Any]:
        """构建一个小而稳定的摘要，避免直接暴露原始 checkpoint 状态。"""
        if not isinstance(channel_values, dict):
            return {}

        stage_summaries = (
            channel_values.get("stage_summaries")
            if isinstance(channel_values.get("stage_summaries"), dict)
            else {}
        )
        metrics = (
            channel_values.get("metrics")
            if isinstance(channel_values.get("metrics"), dict)
            else {}
        )
        loop_counts = (
            channel_values.get("loop_counts")
            if isinstance(channel_values.get("loop_counts"), dict)
            else {}
        )
        stage_summary_map = CheckpointManager._string_key_dict(stage_summaries)
        metric_map = CheckpointManager._string_key_dict(metrics)
        loop_count_map = CheckpointManager._string_key_dict(loop_counts)
        messages = channel_values.get("messages")
        summary: dict[str, Any] = {
            "schema_version": channel_values.get("schema_version"),
            "field_count": len(channel_values),
            "field_names": sorted(str(key) for key in channel_values.keys()),
            "message_count": len(messages) if isinstance(messages, list) else 0,
            "stage_summary_keys": sorted(str(key) for key in stage_summary_map.keys()),
            "metric_keys": sorted(str(key) for key in metric_map.keys()),
            "loop_counts": {
                "total_rounds": int(loop_count_map.get("total_rounds") or 0),
                "retrieval_retries": int(loop_count_map.get("retrieval_retries") or 0),
                "generation_retries": int(loop_count_map.get("generation_retries") or 0),
            },
        }
        checkpoint_restore = (
            stage_summary_map.get("checkpoint_restore")
            if isinstance(stage_summary_map.get("checkpoint_restore"), dict)
            else None
        )
        if checkpoint_restore is not None:
            summary["checkpoint_restore"] = checkpoint_restore
        return summary

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
