from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# 统一的 Redis 客户端类型（asyncio）
RedisClient = Redis


def create_redis_client(settings: Settings | None = None) -> RedisClient:
    """创建带 decode_responses 的 Redis 客户端。"""
    cfg = settings or get_settings()
    return Redis.from_url(
        cfg.redis_url,
        decode_responses=True,
        socket_timeout=cfg.redis_socket_timeout_seconds,
        socket_connect_timeout=cfg.redis_socket_connect_timeout_seconds,
    )


async def close_redis_client(redis: RedisClient | None) -> None:
    """关闭 Redis 客户端（尽力而为）。"""
    if redis is None:
        return
    try:
        await redis.aclose()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Redis client close 失败", extra={"error": str(exc)})
