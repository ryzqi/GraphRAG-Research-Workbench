from __future__ import annotations

from functools import lru_cache

import httpx

from app.core.settings import Settings, get_settings


def _build_timeout(settings: Settings) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.http_timeout_connect_seconds,
        read=settings.http_timeout_read_seconds,
        write=settings.http_timeout_write_seconds,
        pool=settings.http_timeout_pool_seconds,
    )


def _build_limits(settings: Settings) -> httpx.Limits:
    return httpx.Limits(
        max_connections=settings.http_max_connections,
        max_keepalive_connections=settings.http_max_keepalive_connections,
        keepalive_expiry=settings.http_keepalive_expiry_seconds,
    )


def create_http_client(settings: Settings | None = None) -> httpx.AsyncClient:
    cfg = settings or get_settings()
    return httpx.AsyncClient(timeout=_build_timeout(cfg), limits=_build_limits(cfg))


@lru_cache
def get_shared_http_client() -> httpx.AsyncClient:
    settings = get_settings()
    return create_http_client(settings)


async def close_shared_http_client() -> None:
    client = get_shared_http_client()
    await client.aclose()
    get_shared_http_client.cache_clear()
