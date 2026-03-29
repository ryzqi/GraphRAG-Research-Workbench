import json

from langchain.messages import ToolMessage

from app.schemas.chats import EvidenceItem
from app.search.web.citations import (
    append_compact_citations_to_answer,
    extract_external_evidence_from_messages,
)


def test_append_compact_citations_to_answer_renders_compact_entries() -> None:
    answer = "这是最终回答。"
    evidence = [
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://docs.langchain.com/oss/python/langchain-mcp"},
            excerpt="LangChain MCP Python 文档",
            citation_source="https://docs.langchain.com/oss/python/langchain-mcp",
            citation_title="MCP - Docs by LangChain",
        ),
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools"},
            excerpt="MCP Tools 文档",
            citation_source="https://docs.langchain.com/oss/javascript/deepagents/cli/mcp-tools",
            citation_title="MCP Tools - Docs by LangChain",
        ),
    ]

    result = append_compact_citations_to_answer(answer, evidence)

    assert result == (
        "这是最终回答。\n\n"
        "参考来源\n"
        "[1] docs.langchain.com - MCP - Docs by LangChain\n"
        "[2] docs.langchain.com - MCP Tools - Docs by LangChain"
    )


def test_append_compact_citations_to_answer_merges_existing_reference_block() -> None:
    answer = (
        "这是最终回答。\n\n"
        "参考来源\n"
        "[1] docs.langchain.com - MCP - Docs by LangChain"
    )
    evidence = [
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://docs.langchain.com/oss/python/langchain-mcp"},
            excerpt="LangChain MCP Python 文档",
            citation_source="https://docs.langchain.com/oss/python/langchain-mcp",
            citation_title="MCP - Docs by LangChain",
        ),
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://help.openai.com/en/articles/9237897-chatgpt-search"},
            excerpt="ChatGPT Search Help Center",
            citation_source="https://help.openai.com/en/articles/9237897-chatgpt-search",
            citation_title="ChatGPT search | OpenAI Help Center",
        ),
    ]

    result = append_compact_citations_to_answer(answer, evidence)

    assert result == (
        "这是最终回答。\n\n"
        "参考来源\n"
        "[1] docs.langchain.com - MCP - Docs by LangChain\n"
        "[2] help.openai.com - ChatGPT search | OpenAI Help Center"
    )


def test_extract_external_evidence_from_messages_supports_compacted_web_search_payload() -> None:
    messages = [
        ToolMessage(
            tool_call_id="call_web_search_1",
            name="web_search",
            content=json.dumps(
                {
                    "results": [
                        {
                            "title": "MCP - Docs by LangChain",
                            "url": "https://docs.langchain.com/oss/python/langchain-mcp",
                            "snippet": "官方 MCP 文档摘要",
                            "source": "tavily",
                            "domain": "docs.langchain.com",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        )
    ]

    evidence = extract_external_evidence_from_messages(messages)

    assert len(evidence) == 1
    assert evidence[0].citation_title == "MCP - Docs by LangChain"
    assert evidence[0].citation_source == "https://docs.langchain.com/oss/python/langchain-mcp"
    assert evidence[0].locator == {
        "source": "https://docs.langchain.com/oss/python/langchain-mcp",
        "url": "https://docs.langchain.com/oss/python/langchain-mcp",
        "material_title": "MCP - Docs by LangChain",
        "provider": "tavily",
        "domain": "docs.langchain.com",
    }
