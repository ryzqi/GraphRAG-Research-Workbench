from __future__ import annotations

from app.agents.tools import web_search
from app.agents.tools.web_search_builders import (
    build_search_providers,
    build_search_retrievers,
    has_jina_read_provider,
    has_web_extract_provider,
    has_web_search_provider,
)
from app.core.settings import Settings
from app.search.web.retrievers import (
    ProviderSearchRetriever,
    SearxngSearchRetriever,
    TavilySearchRetriever,
)


class _StubProvider:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def search(self, **kwargs: object) -> object:
        raise AssertionError(f"unexpected search call: {kwargs}")


def test_web_search_builder_helpers_and_reexports() -> None:
    settings = Settings(
        web_search_api_key="test-key",
        searxng_search_enabled=False,
        jina_read_enabled=True,
        jina_read_base_url="https://r.jina.ai",
    )

    assert has_web_search_provider(settings) is True
    assert has_web_extract_provider(settings) is True
    assert has_jina_read_provider(settings) is True
    provider_names = [provider.provider_name for provider in build_search_providers(settings)]
    assert "tavily" in provider_names
    assert web_search.has_web_search_provider is has_web_search_provider
    assert web_search.has_web_extract_provider is has_web_extract_provider
    assert web_search.has_jina_read_provider is has_jina_read_provider
    assert web_search.build_search_providers is build_search_providers
    assert web_search.build_search_retrievers is build_search_retrievers


def test_build_search_retrievers_wraps_known_and_generic_providers() -> None:
    retrievers = build_search_retrievers(
        [
            _StubProvider("tavily"),
            _StubProvider("searxng"),
            _StubProvider("custom"),
        ]
    )

    assert isinstance(retrievers[0], TavilySearchRetriever)
    assert isinstance(retrievers[1], SearxngSearchRetriever)
    assert isinstance(retrievers[2], ProviderSearchRetriever)
