from app.core.settings import Settings
from app.schemas.chats import WebSearchProviderStatusRead
import app.services.web_search_status_service as web_search_status_service
from app.search.web.health import build_overall_web_search_status


def test_build_overall_web_search_status_returns_degraded_when_provider_partially_fails() -> None:
    status = build_overall_web_search_status(
        [
            WebSearchProviderStatusRead(
                name="tavily",
                configured=True,
                verified=True,
                healthy=True,
                mode="healthy",
                latency_ms=420,
                error=None,
            ),
            WebSearchProviderStatusRead(
                name="searxng",
                configured=True,
                verified=True,
                healthy=False,
                mode="down",
                latency_ms=5000,
                error="timeout",
            ),
        ]
    )

    assert status.configured is True
    assert status.verified is True
    assert status.mode == "degraded"
    assert [provider.name for provider in status.providers] == ["tavily", "searxng"]


def test_build_overall_web_search_status_returns_down_when_no_provider_is_healthy() -> None:
    status = build_overall_web_search_status(
        [
            WebSearchProviderStatusRead(
                name="tavily",
                configured=True,
                verified=True,
                healthy=False,
                mode="down",
                latency_ms=900,
                error="quota exceeded",
            ),
            WebSearchProviderStatusRead(
                name="searxng",
                configured=True,
                verified=True,
                healthy=False,
                mode="down",
                latency_ms=5000,
                error="timeout",
            ),
        ]
    )

    assert status.mode == "down"


async def test_get_web_search_status_returns_provider_aware_down_when_unconfigured(monkeypatch) -> None:
    web_search_status_service._cached_status = None
    web_search_status_service._cached_expires_at = 0.0
    monkeypatch.setattr(web_search_status_service, "build_search_providers", lambda *, settings: [])
    monkeypatch.setattr(web_search_status_service, "has_jina_read_provider", lambda settings: False)

    status = await web_search_status_service.get_web_search_status(
        settings=Settings(
            _env_file=None,
        )
    )

    assert status.configured is False
    assert status.verified is False
    assert status.mode == "down"
    assert [provider.name for provider in status.providers] == [
        "tavily",
        "searxng",
        "jina_reader",
    ]
    assert all(provider.configured is False for provider in status.providers)
