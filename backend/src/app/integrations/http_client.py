from __future__ import annotations

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


async def close_http_client(client: httpx.AsyncClient | None) -> None:
    """关闭 httpx 客户端（尽力而为）。"""
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:  # pragma: no cover - best effort
        return
