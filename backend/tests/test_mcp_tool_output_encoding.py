import json
from types import SimpleNamespace

import pytest

from app.agents.tool_calling import registry as registry_module
from app.agents.tool_calling import utils as utils_module
from app.core.settings import Settings
from app.integrations import mcp_adapters as adapters_module
from app.integrations.mcp_adapters import McpToolEntry


def _make_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        mcp_enabled=True,
        jina_reader_api_key="",
        **overrides,
    )


class _FakeMcpTool:
    name = "echo"
    description = "echo"
    args_schema = None

    async def ainvoke(self, _kwargs):  # noqa: ANN001, ANN201
        return {"payload": "x" * 1000}


class _FailingMcpTool:
    name = "broken"
    description = "broken"
    args_schema = None

    async def ainvoke(self, _kwargs):  # noqa: ANN001, ANN201
        raise RuntimeError("boom-" + "x" * 1000)


def test_format_audit_payload_keeps_preencoded_string() -> None:
    payload = '{"ok": true, "content": {"payload": "value"}}'

    formatted = adapters_module._format_audit_payload(payload, max_chars=200)

    assert formatted == payload


@pytest.mark.asyncio
async def test_mcp_tool_output_path_encodes_payload_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ext = SimpleNamespace(id="ext-1", name="Ext")
    settings = _make_settings()
    dumps_calls: list[str] = []
    original_dumps = json.dumps

    def _counting_dumps(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        dumps_calls.append(type(args[0]).__name__)
        return original_dumps(*args, **kwargs)

    monkeypatch.setattr(json, "dumps", _counting_dumps)

    tools, _ = await registry_module.build_tool_registry(
        settings=settings,
        extensions=[ext],
        mcp_entries=[
            McpToolEntry(
                extension=ext,
                tool=_FakeMcpTool(),
                raw_tool_name="echo",
            )
        ],
        include_web_search=False,
        include_web_extract=False,
        include_web_crawl=False,
        include_mcp=True,
        tool_output_max_chars=5000,
    )

    tool = next(item for item in tools if item.name.startswith("mcp__"))

    result = await tool.ainvoke({})
    audit_payload = adapters_module._format_audit_payload(result, max_chars=5000)

    assert audit_payload == result
    assert dumps_calls == ["dict"]


@pytest.mark.asyncio
async def test_mcp_tool_error_path_truncates_encoded_payload_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ext = SimpleNamespace(id="ext-1", name="Ext")
    settings = _make_settings()
    truncate_inputs: list[str] = []
    original_truncate = utils_module.truncate_tool_output

    def _counting_truncate(
        text: str,
        max_chars: int = utils_module.DEFAULT_TOOL_OUTPUT_MAX_CHARS,
    ) -> tuple[str, bool]:
        truncate_inputs.append(text)
        return original_truncate(text, max_chars)

    monkeypatch.setattr(utils_module, "truncate_tool_output", _counting_truncate)
    monkeypatch.setattr(
        registry_module,
        "truncate_tool_output",
        _counting_truncate,
        raising=False,
    )

    tools, _ = await registry_module.build_tool_registry(
        settings=settings,
        extensions=[ext],
        mcp_entries=[
            McpToolEntry(
                extension=ext,
                tool=_FailingMcpTool(),
                raw_tool_name="broken",
            )
        ],
        include_web_search=False,
        include_web_extract=False,
        include_web_crawl=False,
        include_mcp=True,
        tool_output_max_chars=200,
    )

    tool = next(item for item in tools if item.name.startswith("mcp__"))

    result = await tool.ainvoke({})

    assert len(truncate_inputs) == 1
    assert truncate_inputs[0].startswith('{"ok": false')
    assert "（输出已截断）" in result
