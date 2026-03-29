import json

from app.agents.tool_calling.web_tool_payloads import compact_builtin_external_output


def test_compact_web_search_output_preserves_query_plan_and_compact_results() -> None:
    payload = {
        "query": "langchain mcp docs",
        "query_plan": {
            "original_query": "langchain mcp docs",
            "rewritten_queries": [
                "langchain mcp docs",
                "site:docs.langchain.com langchain mcp docs",
            ],
        },
        "results": [
            {
                "title": "MCP - Docs by LangChain",
                "url": "https://docs.langchain.com/oss/python/langchain-mcp",
                "snippet": "官方 MCP 文档摘要",
                "source": "tavily",
                "domain": "docs.langchain.com",
            }
        ],
        "provider_reports": [
            {
                "provider": "tavily",
                "ok": True,
                "result_count": 1,
                "elapsed_ms": 120,
                "error": None,
            }
        ],
        "merged_count": 1,
        "elapsed_ms": 150,
        "error": None,
    }

    text = compact_builtin_external_output("web_search", json.dumps(payload, ensure_ascii=False), 1000)
    compacted = json.loads(text)

    assert compacted["query_plan"]["rewritten_queries"] == [
        "langchain mcp docs",
        "site:docs.langchain.com langchain mcp docs",
    ]
    assert compacted["results"][0]["source"] == "tavily"
