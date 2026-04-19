"""web_search 每条结果带 snippet_locator。"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document

from app.agents.tools.web_search_builders import build_web_search_tool
from app.core.settings import Settings
from app.search.web.documents import document_to_result


def _make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, web_search_api_key="test-key", **overrides)


def test_web_search_emits_snippet_locator() -> None:
    settings = _make_settings()
    fake_output = {
        "query": "q",
        "results": [
            {
                "title": "t",
                "url": "https://example.com/",
                "snippet": "A snippet of text with enough words to reason on.",
                "provider": "tavily",
                "domain": "example.com",
            }
        ],
        "provider_reports": [],
        "merged_count": 1,
        "elapsed_ms": 5,
        "error": None,
        "cache_hit": False,
    }
    with patch(
        "app.agents.tools.web_search_builders._invoke_web_search",
        new=AsyncMock(return_value=fake_output),
    ):
        tool = build_web_search_tool(settings, search_providers=[], read_provider=None)
        output = asyncio.run(tool.ainvoke({"query": "q"}))
    payload = json.loads(output)
    assert payload["results"][0]["snippet_locator"]


def test_document_to_result_emits_snippet_locator() -> None:
    result = document_to_result(
        Document(
            page_content="A snippet of text with enough words to reason on.",
            metadata={
                "title": "Example title",
                "url": "https://example.com/",
                "provider": "tavily",
            },
        )
    )
    assert result["snippet_locator"] == "Example title"
