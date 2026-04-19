from __future__ import annotations

import httpx
import pytest

from app.agents.tools.web_search_client import WebSearchClient
from app.agents.tools.web_search_models import (
    WebCrawlArgs,
    WebExtractArgs,
    WebResearchArgs,
)
from app.core.settings import Settings


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, web_search_api_key="test-key", **overrides)


class _DummyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"results": []}


async def test_call_tavily_http_uses_injected_client_timeout() -> None:
    captured: dict[str, object] = {}

    class _TrackingClient:
        def __init__(self) -> None:
            self.timeout = httpx.Timeout(12.0)

        async def request(self, method: str, url: str, **kwargs: object) -> _DummyResponse:
            captured["method"] = method
            captured["url"] = url
            captured["timeout"] = kwargs.get("timeout")
            return _DummyResponse()

    client = _TrackingClient()
    subject = WebSearchClient(settings=_make_settings(), http_client=client)  # type: ignore[arg-type]

    await subject._call_tavily_http(
        method="POST",
        path="/search",
        json_payload={"query": "hello"},
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["timeout"] is client.timeout


async def test_call_tavily_http_requires_injected_client(monkeypatch) -> None:
    subject = WebSearchClient(settings=_make_settings())

    with pytest.raises(RuntimeError, match="http_client"):
        await subject._call_tavily_http(
            method="GET",
            path="/research/r-123",
        )


async def test_sdk_calls_use_explicit_timeout(monkeypatch) -> None:
    captured: list[tuple[str, object | None]] = []
    subject = WebSearchClient(settings=_make_settings())

    async def _fake_call(method_name: str, **kwargs: object) -> dict[str, object]:
        captured.append((method_name, kwargs.get("timeout")))
        if method_name == "research":
            return {"status": "completed", "sources": []}
        return {"results": []}

    monkeypatch.setattr(subject, "_call_tavily", _fake_call)

    await subject.extract(
        WebExtractArgs.model_validate({"urls": ["https://example.com"]})
    )
    await subject.crawl(
        WebCrawlArgs.model_validate({"url": "https://example.com"})
    )
    await subject.research(
        WebResearchArgs.model_validate({"query": "timeout behavior"})
    )

    assert captured == [
        ("extract", 30.0),
        ("crawl", 150.0),
        ("research", 30.0),
    ]


def test_timeout_errors_are_retryable() -> None:
    subject = WebSearchClient(settings=_make_settings())

    assert subject._is_retryable(httpx.ReadTimeout("timed out")) is True
