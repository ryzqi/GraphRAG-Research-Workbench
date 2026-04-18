"""LangGraph Postgres 连接池共享单例。

为 Checkpoint 与 Store 提供同一个 AsyncConnectionPool，
避免 `from_conn_string()` 的单连接路径在高并发下串行化。
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.settings import Settings

logger = logging.getLogger(__name__)


def _to_psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class LangGraphPostgresPool:
    """LangGraph 持久化层的共享连接池。"""

    _pool: AsyncConnectionPool | None = None
    _initialized: bool = False
    _conn_string: str | None = None

    @classmethod
    async def initialize(cls, settings: Settings) -> None:
        if cls._initialized:
            return

        conn_string = _to_psycopg_url(settings.database_url)
        pool = AsyncConnectionPool(
            conn_string,
            min_size=settings.langgraph_postgres_pool_min_size,
            max_size=settings.langgraph_postgres_pool_max_size,
            timeout=settings.langgraph_postgres_pool_timeout_seconds,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        await pool.open()

        cls._pool = pool
        cls._initialized = True
        cls._conn_string = conn_string
        logger.info(
            "LangGraph Postgres pool initialized",
            extra={
                "min_size": settings.langgraph_postgres_pool_min_size,
                "max_size": settings.langgraph_postgres_pool_max_size,
                "timeout_seconds": settings.langgraph_postgres_pool_timeout_seconds,
            },
        )

    @classmethod
    async def shutdown(cls) -> None:
        pool = cls._pool
        cls._pool = None
        cls._initialized = False
        cls._conn_string = None

        if pool is None:
            return
        await pool.close()

    @classmethod
    def get_pool(cls) -> AsyncConnectionPool:
        if not cls._initialized or cls._pool is None:
            raise RuntimeError("LangGraphPostgresPool not initialized")
        return cls._pool

    @classmethod
    def status(cls) -> dict[str, Any]:
        if not cls._initialized or cls._pool is None:
            return {
                "status": "uninitialized",
                "initialized": False,
                "stats": {},
            }

        get_stats = getattr(cls._pool, "get_stats", None)
        stats = get_stats() if callable(get_stats) else {}
        return {
            "status": "ready",
            "initialized": True,
            "stats": stats,
        }
