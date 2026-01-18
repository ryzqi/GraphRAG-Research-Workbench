from __future__ import annotations

from functools import lru_cache

from redis.asyncio import Redis

from app.core.settings import get_settings

# 统一的 Redis 客户端类型（asyncio）
RedisClient = Redis


@lru_cache
def get_redis() -> RedisClient:
    """获取带 decode_responses 的 Redis 客户端单例。"""
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
    )
