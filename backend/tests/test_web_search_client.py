from __future__ import annotations

import httpx
import pytest

from app.agents.tools.web_search_client import WebSearchClient
from app.core.settings import Settings


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"results": []}


class _ProxyLikeHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                **kwargs,
            }
        )
        return _FakeResponse()


@pytest.mark.asyncio
async def test_call_tavily_http_uses_settings_timeout_when_client_has_no_timeout() -> None:
    settings = Settings(WEB_SEARCH_API_KEY="test-key")
    http_client = _ProxyLikeHttpClient()
    client = WebSearchClient(settings=settings, http_client=http_client)  # type: ignore[arg-type]

    await client._call_tavily_http(  # type: ignore[attr-defined]
        method="POST",
        path="/search",
        json_payload={"query": "agent frameworks"},
    )

    assert len(http_client.calls) == 1
    timeout = http_client.calls[0]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == settings.http_timeout_connect_seconds
    assert timeout.read == settings.http_timeout_read_seconds
    assert timeout.write == settings.http_timeout_write_seconds
    assert timeout.pool == settings.http_timeout_pool_seconds
