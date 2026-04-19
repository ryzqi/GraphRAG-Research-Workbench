"""研究工具输出 excerpt_candidates。"""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.tools.research_tools import (
    build_arxiv_fetch_tool,
    build_arxiv_search_tool,
)


def _fake_arxiv_result(title: str, summary: str):
    return SimpleNamespace(
        title=title,
        summary=summary,
        authors=[SimpleNamespace(name="A")],
        entry_id="http://arxiv.org/abs/2501.00001",
        get_short_id=lambda: "2501.00001",
        published=datetime.now(timezone.utc),
        pdf_url="http://arxiv.org/pdf/2501.00001",
        primary_category="cs.AI",
        categories=["cs.AI"],
    )


def test_arxiv_search_emits_excerpt_candidates() -> None:
    tool = build_arxiv_search_tool()
    fake = _fake_arxiv_result(
        "Agentic RAG",
        "This paper presents agentic RAG. First finding. Second finding.",
    )
    with patch("app.agents.tools.research_tools.arxiv.Client") as client_cls:
        client_cls.return_value.results.return_value = iter([fake])
        output = asyncio.run(tool.ainvoke({"query": "rag", "max_results": 1}))
    payload = json.loads(output)
    assert payload["error"] is None
    candidates = payload["results"][0]["excerpt_candidates"]
    assert len(candidates) >= 1
    assert all(40 <= len(item["text"]) <= 400 for item in candidates)


def test_arxiv_fetch_emits_excerpt_candidates() -> None:
    tool = build_arxiv_fetch_tool()
    fake = _fake_arxiv_result("X", "Abstract with enough words. " * 10)
    with patch("app.agents.tools.research_tools.arxiv.Client") as client_cls:
        client_cls.return_value.results.return_value = iter([fake])
        output = asyncio.run(tool.ainvoke({"ids": ["2501.00001"]}))
    payload = json.loads(output)
    assert payload["results"][0]["excerpt_candidates"][0]["text"]
