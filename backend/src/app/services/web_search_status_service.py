"""网页搜索状态探测。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.config.policy_loader import load_research_policy
from app.agents.tools.web_search import build_search_providers, has_jina_read_provider
from app.agents.tools.web_search_providers.jina_provider import JinaReadProvider
from app.core.settings import Settings
from app.schemas.chats import WebSearchProviderStatusRead, WebSearchStatusRead
from app.search.web.health import build_overall_web_search_status

logger = logging.getLogger(__name__)

_status_lock = asyncio.Lock()
_cached_status: WebSearchStatusRead | None = None
_cached_expires_at = 0.0


def _monotonic() -> float:
    return time.monotonic()


def _status_probe_policy():
    return load_research_policy().status_probe


def _provider_order() -> tuple[str, ...]:
    return tuple(_status_probe_policy().provider_order)


def _search_provider_names() -> set[str]:
    return set(_status_probe_policy().search_provider_names)


def _build_provider_status(
    *,
    name: str,
    configured: bool,
    verified: bool,
    healthy: bool,
    latency_ms: int | None = None,
    error: str | None = None,
) -> WebSearchProviderStatusRead:
    return WebSearchProviderStatusRead(
        name=name,  # type: ignore[arg-type]
        configured=configured,
        verified=verified,
        healthy=healthy,
        mode="healthy" if healthy else "down",
        latency_ms=latency_ms,
        error=error,
    )


def _unconfigured_provider_status(name: str) -> WebSearchProviderStatusRead:
    return _build_provider_status(
        name=name,
        configured=False,
        verified=False,
        healthy=False,
    )


def _stringify_error(error: object) -> str | None:
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        detail = str(error.get("detail") or "").strip()
        parts = [part for part in [message, detail] if part]
        return " | ".join(parts) if parts else None
    text = str(error or "").strip()
    return text or None


def _empty_status(*, settings: Settings) -> WebSearchStatusRead:
    provider_order = _provider_order()
    providers = {name: _unconfigured_provider_status(name) for name in provider_order}
    if has_jina_read_provider(settings):
        providers["jina_reader"] = _build_provider_status(
            name="jina_reader",
            configured=True,
            verified=False,
            healthy=False,
            error="缺少可用的搜索 provider",
        )
    return WebSearchStatusRead(
        configured=False,
        verified=False,
        mode="down",
        providers=[providers[name] for name in provider_order],
    )


async def get_web_search_status(*, settings: Settings) -> WebSearchStatusRead:
    """返回结构化联网状态。"""
    global _cached_status, _cached_expires_at

    now = _monotonic()
    if _cached_status is not None and now < _cached_expires_at:
        return _cached_status

    async with _status_lock:
        now = _monotonic()
        if _cached_status is not None and now < _cached_expires_at:
            return _cached_status

        status = await _probe_web_search_status(settings=settings)
        _cached_status = status
        _cached_expires_at = _monotonic() + float(
            _status_probe_policy().cache_ttl_seconds
        )
        return status


async def _probe_search_provider(
    provider: Any,
) -> WebSearchProviderStatusRead:
    status_probe_policy = _status_probe_policy()
    provider_name = str(getattr(provider, "provider_name", "")).strip() or "tavily"
    start = time.perf_counter()
    try:
        response = await provider.search(
            query=status_probe_policy.search_probe_query,
            max_results=1,
            search_depth="basic",
            include_answer=False,
            include_usage=False,
            auto_parameters=False,
        )
    except Exception as exc:  # pragma: no cover - provider 自身异常由状态兜底
        logger.warning(
            "Web 搜索 provider 健康检查失败",
            extra={"provider": provider_name, "error": str(exc)},
        )
        return _build_provider_status(
            name=provider_name,
            configured=True,
            verified=True,
            healthy=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            error=str(exc),
        )

    return _build_provider_status(
        name=provider_name,
        configured=True,
        verified=True,
        healthy=bool(response.report.ok),
        latency_ms=int((time.perf_counter() - start) * 1000),
        error=_stringify_error(response.report.error),
    )


async def _probe_jina_read_provider(
    *,
    settings: Settings,
) -> WebSearchProviderStatusRead:
    status_probe_policy = _status_probe_policy()
    if not has_jina_read_provider(settings):
        return _unconfigured_provider_status("jina_reader")

    provider = JinaReadProvider(settings=settings)
    start = time.perf_counter()
    try:
        payload = await provider.read(
            url=status_probe_policy.jina_probe_url,
        )
    except Exception as exc:  # pragma: no cover - provider 自身异常由状态兜底
        logger.warning("Jina Reader 健康检查失败", extra={"error": str(exc)})
        return _build_provider_status(
            name="jina_reader",
            configured=True,
            verified=True,
            healthy=False,
            latency_ms=int((time.perf_counter() - start) * 1000),
            error=str(exc),
        )

    content = str(payload.get("content") or "").strip()
    title = str(payload.get("title") or "").strip()
    error = _stringify_error(payload.get("error"))
    healthy = not error and bool(content or title)
    return _build_provider_status(
        name="jina_reader",
        configured=True,
        verified=True,
        healthy=healthy,
        latency_ms=int((time.perf_counter() - start) * 1000),
        error=error,
    )


async def _probe_web_search_status(*, settings: Settings) -> WebSearchStatusRead:
    provider_order = _provider_order()
    search_provider_names = _search_provider_names()
    providers_by_name = {
        name: _unconfigured_provider_status(name) for name in provider_order
    }
    search_providers = build_search_providers(settings=settings)
    if not search_providers:
        return _empty_status(settings=settings)

    search_statuses = await asyncio.gather(
        *[_probe_search_provider(provider) for provider in search_providers]
    )
    for status in search_statuses:
        providers_by_name[status.name] = status

    jina_status = await _probe_jina_read_provider(
        settings=settings,
    )
    providers_by_name[jina_status.name] = jina_status

    participating_providers = [
        providers_by_name[name]
        for name in provider_order
        if providers_by_name[name].configured
        and (name == "jina_reader" or name in search_provider_names)
    ]
    overall_status = build_overall_web_search_status(participating_providers)
    return WebSearchStatusRead(
        configured=overall_status.configured,
        verified=overall_status.verified,
        mode=overall_status.mode,
        providers=[providers_by_name[name] for name in provider_order],
    )
