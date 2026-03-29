"""provider-aware 健康状态聚合。"""

from __future__ import annotations

from app.schemas.chats import (
    WebSearchProviderStatusRead,
    WebSearchStatusRead,
)


def build_overall_web_search_status(
    providers: list[WebSearchProviderStatusRead],
) -> WebSearchStatusRead:
    configured = any(provider.configured for provider in providers)
    verified = any(provider.verified for provider in providers)
    healthy_count = sum(1 for provider in providers if provider.healthy)

    if not configured:
        mode = "down"
    elif healthy_count == 0:
        mode = "down"
    elif healthy_count == len(providers):
        mode = "healthy"
    else:
        mode = "degraded"

    return WebSearchStatusRead(
        configured=configured,
        verified=verified,
        mode=mode,
        providers=providers,
    )
