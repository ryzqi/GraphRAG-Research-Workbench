"""tavily_extract / tavily_crawl 输出 excerpt_candidates。"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.agents.tools.research_tools import (
    build_tavily_crawl_tool,
    build_tavily_extract_tool,
)
from app.core.settings import Settings


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, web_search_api_key="test-key", **overrides)


def _fake_extract_result() -> dict:
    return {
        "results": [
            {
                "url": "https://example.com/a",
                "raw_content": "Headline paragraph. " + ("extra content. " * 40),
            }
        ]
    }


def test_tavily_extract_emits_excerpt_candidates() -> None:
    settings = _make_settings()
    with patch(
        "app.agents.tools.research_tools.WebSearchClient.extract",
        new=AsyncMock(return_value=_fake_extract_result()),
    ):
        tool = build_tavily_extract_tool(settings)
        output = asyncio.run(tool.ainvoke({"urls": ["https://example.com/a"]}))
    payload = json.loads(output)
    assert payload["results"][0]["excerpt_candidates"]
    assert all(
        40 <= len(candidate["text"]) <= 400
        for candidate in payload["results"][0]["excerpt_candidates"]
    )


def test_tavily_crawl_emits_excerpt_candidates() -> None:
    settings = _make_settings()
    with patch(
        "app.agents.tools.research_tools.WebSearchClient.crawl",
        new=AsyncMock(
            return_value={
                "results": [
                    {"url": "https://example.com/a/1", "raw_content": "word " * 200}
                ]
            }
        ),
    ):
        tool = build_tavily_crawl_tool(settings)
        output = asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))
    payload = json.loads(output)
    assert payload["results"][0]["excerpt_candidates"]
