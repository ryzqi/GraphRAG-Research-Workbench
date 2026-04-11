"""网页搜索、抽取、爬取与研究工具 façade。"""

from __future__ import annotations

from app.agents.tools.web_search_builders import (
    build_jina_read_tool,
    build_search_providers,
    build_search_retrievers,
    build_web_crawl_tool,
    build_web_extract_tool,
    build_web_search_tool,
    has_jina_read_provider,
    has_web_extract_provider,
    has_web_search_provider,
)
from app.agents.tools.web_search_client import WebSearchClient
from app.agents.tools.web_search_models import (
    JinaReadArgs,
    WebCrawlArgs,
    WebExtractArgs,
    WebResearchArgs,
    WebSearchArgs,
)

__all__ = [
    "JinaReadArgs",
    "WebSearchArgs",
    "WebExtractArgs",
    "WebCrawlArgs",
    "WebResearchArgs",
    "WebSearchClient",
    "has_web_search_provider",
    "has_web_extract_provider",
    "has_jina_read_provider",
    "build_search_providers",
    "build_search_retrievers",
    "build_web_search_tool",
    "build_jina_read_tool",
    "build_web_extract_tool",
    "build_web_crawl_tool",
]
