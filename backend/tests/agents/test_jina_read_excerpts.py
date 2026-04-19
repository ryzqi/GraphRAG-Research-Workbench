"""jina_read 输出 excerpt_candidates。"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.agents.tools.web_search_builders import build_jina_read_tool
from app.core.settings import Settings


def _make_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        jina_read_enabled=True,
        jina_read_base_url="https://r.jina.ai/http://",
        **overrides,
    )


def test_jina_read_emits_excerpt_candidates() -> None:
    settings = _make_settings()
    with patch(
        "app.agents.tools.web_search_builders._invoke_jina_read",
        new=AsyncMock(
            return_value={
                "url": "https://example.com/a",
                "title": "Example",
                "content": "Paragraph one. " + ("supporting detail. " * 40),
                "error": None,
            }
        ),
    ):
        tool = build_jina_read_tool(settings)
        output = asyncio.run(tool.ainvoke({"url": "https://example.com/a"}))
    payload = json.loads(output)
    assert payload["excerpt_candidates"]
    assert all(
        40 <= len(candidate["text"]) <= 400
        for candidate in payload["excerpt_candidates"]
    )
