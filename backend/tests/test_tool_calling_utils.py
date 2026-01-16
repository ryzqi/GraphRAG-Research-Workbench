from langchain_core.messages import AIMessage, ToolMessage

from app.agents.tool_calling.registry import ToolMeta
from app.agents.tool_calling.utils import (
    TRUNCATION_MARK,
    extract_pending_tool_calls,
    extract_tool_results,
    is_mcp_tool_name,
    make_mcp_tool_name,
    parse_mcp_tool_name,
    truncate_tool_output,
)


def test_mcp_tool_name_roundtrip() -> None:
    name = make_mcp_tool_name("ext:1", "search tool")
    assert name == "mcp__ext_1__search_tool"
    assert is_mcp_tool_name(name) is True
    assert parse_mcp_tool_name(name) == ("ext_1", "search_tool")

    assert is_mcp_tool_name("web_search") is False
    assert parse_mcp_tool_name("web_search") is None


def test_truncate_tool_output_adds_marker() -> None:
    text = "0123456789" * 10
    max_chars = len(TRUNCATION_MARK) + 5
    out, truncated = truncate_tool_output(text, max_chars)
    assert truncated is True
    assert out.endswith(TRUNCATION_MARK)
    assert len(out) <= max_chars


def test_extract_pending_tool_calls_filters_external() -> None:
    meta_by_name = {
        "internal": ToolMeta(
            tool_name="internal",
            raw_tool_name="internal",
            extension_id="builtin",
            extension_name="内置工具",
            is_builtin=True,
            is_external=False,
        ),
        "web_search": ToolMeta(
            tool_name="web_search",
            raw_tool_name="web_search",
            extension_id="builtin",
            extension_name="内置工具",
            is_builtin=True,
            is_external=True,
        ),
    }
    msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "web_search", "args": {"q": "x"}, "id": "call_1"},
            {"name": "internal", "args": {"x": 1}, "id": "call_2"},
        ],
    )

    pending = extract_pending_tool_calls([msg], meta_by_name, external_only=True)
    assert pending == [
        {
            "extension_id": "builtin",
            "extension_name": "内置工具",
            "tool_name": "web_search",
            "args": {"q": "x"},
            "is_builtin": True,
        }
    ]

    pending_all = extract_pending_tool_calls([msg], meta_by_name, external_only=False)
    assert len(pending_all) == 2


def test_extract_tool_results_matches_tool_messages() -> None:
    meta_by_name = {
        "web_search": ToolMeta(
            tool_name="web_search",
            raw_tool_name="web_search",
            extension_id="builtin",
            extension_name="内置工具",
            is_builtin=True,
            is_external=True,
        )
    }

    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "web_search", "args": {"query": "a"}, "id": "call_1"},
            {"name": "web_search", "args": {"query": "b"}, "id": "call_2"},
        ],
    )
    ok = ToolMessage(tool_call_id="call_1", content="ok", status="success")
    err = ToolMessage(tool_call_id="call_2", content="boom", status="error")

    results = extract_tool_results([ai, ok, err], meta_by_name)
    assert results == [
        {
            "extension_id": "builtin",
            "extension_name": "内置工具",
            "tool_name": "web_search",
            "args": {"query": "a"},
            "is_builtin": True,
            "success": True,
            "output": "ok",
        },
        {
            "extension_id": "builtin",
            "extension_name": "内置工具",
            "tool_name": "web_search",
            "args": {"query": "b"},
            "is_builtin": True,
            "success": False,
            "output": "boom",
        },
    ]
