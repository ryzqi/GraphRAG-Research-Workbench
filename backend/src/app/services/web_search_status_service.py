"""Web 搜索状态探测。"""

from __future__ import annotations

import asyncio
import logging
import time

from app.agents.tools.web_search import WebSearchArgs, WebSearchClient
from app.core.settings import Settings
from app.schemas.chats import WebSearchStatusRead

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300.0
_status_lock = asyncio.Lock()
_cached_status: WebSearchStatusRead | None = None
_cached_expires_at = 0.0


async def get_web_search_status(*, settings: Settings) -> WebSearchStatusRead:
    """返回结构化联网状态。"""
    global _cached_status, _cached_expires_at

    if not settings.web_search_api_key:
        return WebSearchStatusRead(
            configured=False,
            verified=False,
            healthy=False,
        )

    now = time.monotonic()
    if _cached_status is not None and now < _cached_expires_at:
        return _cached_status

    async with _status_lock:
        now = time.monotonic()
        if _cached_status is not None and now < _cached_expires_at:
            return _cached_status

        status = await _probe_web_search_status(settings=settings)
        _cached_status = status
        _cached_expires_at = time.monotonic() + _CACHE_TTL_SECONDS
        return status


async def _probe_web_search_status(*, settings: Settings) -> WebSearchStatusRead:
    timeout_seconds = min(float(settings.web_search_timeout_seconds), 5.0)
    client = WebSearchClient(settings)
    try:
        output = await client.search(
            WebSearchArgs(
                query="Tavily health check",
                max_results=1,
                search_depth="basic",
                include_answer=False,
                include_usage=False,
                auto_parameters=False,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception as exc:  # pragma: no cover - 失败分支由日志与上层状态兜底
        logger.warning("Web 搜索健康检查失败", extra={"error": str(exc)})
        return WebSearchStatusRead(
            configured=True,
            verified=True,
            healthy=False,
        )

    return WebSearchStatusRead(
        configured=True,
        verified=True,
        healthy=not bool(output.get("error")),
    )
