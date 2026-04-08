import pytest
from pydantic import ValidationError

from app.agents.tools.web_search import WebResearchArgs, WebSearchClient
from app.core.settings import Settings


def _build_settings() -> Settings:
    return Settings(
        web_search_api_key="tvly-test",
        web_search_cache_enabled=False,
    )


def test_web_research_args_accept_current_tavily_citation_formats() -> None:
    args = WebResearchArgs(query="研究 Tavily 最新 SDK", citation_format="apa")

    assert args.citation_format == "apa"

    with pytest.raises(ValidationError):
        WebResearchArgs(query="研究 Tavily 最新 SDK", citation_format="markdown")


@pytest.mark.asyncio
async def test_research_uses_current_tavily_sdk_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WebSearchClient(_build_settings())
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_call(method_name: str, **kwargs: object) -> dict[str, object]:
        calls.append((method_name, kwargs))
        if method_name == "research":
            return {"request_id": "req-sdk", "status": "pending"}
        if method_name == "get_research":
            return {
                "request_id": "req-sdk",
                "status": "completed",
                "content": "最新 research 报告",
                "sources": [
                    {
                        "title": "官方文档",
                        "url": "https://docs.tavily.com",
                        "content": "Research API 用法",
                    }
                ],
                "usage": {"credits": 1},
            }
        raise AssertionError(f"unexpected method: {method_name}")

    async def _fake_write_cache(key: str, value: dict[str, object]) -> None:
        del key, value

    monkeypatch.setattr(client, "_call_tavily", _fake_call)
    monkeypatch.setattr(client, "_write_cache", _fake_write_cache)

    output = await client.research(
        WebResearchArgs(query="研究 Tavily 最新 SDK", citation_format="apa")
    )

    assert len(calls) == 2
    assert calls[0][0] == "research"
    assert calls[0][1]["input"] == "研究 Tavily 最新 SDK"
    assert "query" not in calls[0][1]
    assert calls[0][1]["citation_format"] == "apa"
    assert calls[1] == ("get_research", {"request_id": "req-sdk"})
    assert output["request_id"] == "req-sdk"
    assert output["report"] == "最新 research 报告"
    assert output["results"] == [
        {
            "title": "官方文档",
            "url": "https://docs.tavily.com",
            "snippet": "Research API 用法",
            "published_at": None,
            "raw_content": None,
            "images": None,
            "favicon": None,
            "source": "tavily",
        }
    ]
    assert output["error"] is None


@pytest.mark.asyncio
async def test_research_http_fallback_uses_current_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    client = WebSearchClient(_build_settings())
    http_calls: list[dict[str, object]] = []

    async def _fake_call(method_name: str, **kwargs: object) -> dict[str, object]:
        del kwargs
        if method_name == "research":
            raise RuntimeError("research unsupported")
        raise AssertionError(f"unexpected method: {method_name}")

    async def _fake_http(
        *,
        method: str,
        path: str,
        json_payload: dict[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        http_calls.append(
            {
                "method": method,
                "path": path,
                "json_payload": json_payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "request_id": "req-http",
            "status": "completed",
            "content": "HTTP fallback 报告",
            "sources": [
                {
                    "title": "PyPI",
                    "url": "https://pypi.org/project/tavily-python/",
                    "content": "当前版本信息",
                }
            ],
        }

    async def _fake_write_cache(key: str, value: dict[str, object]) -> None:
        del key, value

    monkeypatch.setattr(client, "_call_tavily", _fake_call)
    monkeypatch.setattr(client, "_call_tavily_http", _fake_http)
    monkeypatch.setattr(client, "_write_cache", _fake_write_cache)

    output = await client.research(WebResearchArgs(query="查询 Tavily 版本"))

    assert len(http_calls) == 1
    assert http_calls[0]["method"] == "POST"
    assert http_calls[0]["path"] == "/research"
    assert http_calls[0]["timeout_seconds"] == 180.0
    assert http_calls[0]["json_payload"]["input"] == "查询 Tavily 版本"
    assert "query" not in http_calls[0]["json_payload"]
    assert http_calls[0]["json_payload"]["citation_format"] == "numbered"
    assert output["request_id"] == "req-http"
    assert output["report"] == "HTTP fallback 报告"
    assert output["results"][0]["url"] == "https://pypi.org/project/tavily-python/"
