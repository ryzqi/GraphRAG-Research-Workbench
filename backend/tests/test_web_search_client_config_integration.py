from __future__ import annotations

from typing import Any

from app.agents.tools.web_search_client import WebSearchClient
from app.agents.tools.web_search_models import WebSearchArgs
from app.core.settings import Settings


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "Result",
                    "url": "https://example.com/result",
                    "content": "snippet",
                }
            ]
        }


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: object = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return _FakeResponse()


async def test_web_search_client_uses_configured_tavily_base_url() -> None:
    http_client = _FakeAsyncClient()
    settings = Settings(
        _env_file=None,
        WEB_SEARCH_API_KEY="test-key",
        TAVILY_BASE_URL="https://proxy.internal/tavily",
    )
    client = WebSearchClient(settings, http_client=http_client)

    await client.search(WebSearchArgs(query="langchain"))

    assert settings.web_search_provider.tavily_base_url == "https://proxy.internal/tavily"
    assert http_client.calls[0]["url"] == "https://proxy.internal/tavily/search"
