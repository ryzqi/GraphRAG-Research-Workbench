from __future__ import annotations

from types import SimpleNamespace
import uuid

import pytest
from langchain.tools import tool as lc_tool

from app.agents.tool_calling import registry as registry_module
from app.models.tool_extension import ExtensionTransport


def _make_settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "mcp_enabled": True,
        "web_search_api_key": "test-key",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _make_extension(
    *,
    extension_id: uuid.UUID | None = None,
    name: str = "alpha",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=extension_id or uuid.uuid4(),
        name=name,
        transport=ExtensionTransport.HTTP,
    )


def _make_async_tool(name: str, result: str):
    async def _tool() -> str:
        """测试用异步工具。"""
        return result

    return lc_tool(name, description=f"{name} test tool")(_tool)


@pytest.fixture(autouse=True)
def _clear_registry_caches() -> None:
    registry_module._STATIC_TOOL_REGISTRY_CACHE.clear()


@pytest.mark.asyncio
async def test_build_tool_registry_cached_reuses_static_section_but_reloads_non_runtime_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings()
    extension = _make_extension()
    counts = {"web_search": 0, "mcp_load": 0}
    redis = object()
    http_client = object()

    monkeypatch.setattr(registry_module, "has_web_search_provider", lambda _s: True)
    monkeypatch.setattr(registry_module, "has_web_extract_provider", lambda _s: False)
    monkeypatch.setattr(registry_module, "has_jina_read_provider", lambda _s: False)

    def _build_web_search_tool(*_args, **_kwargs):
        counts["web_search"] += 1
        return _make_async_tool("web_search", "web")

    async def _load_mcp_tools(*, settings, extensions):  # noqa: ANN001
        counts["mcp_load"] += 1
        assert settings is settings_obj
        assert list(extensions) == [extension]
        return [
            SimpleNamespace(
                extension=extension,
                raw_tool_name="echo",
                tool=_make_async_tool("echo", f"mcp-{counts['mcp_load']}"),
            )
        ]

    settings_obj = settings
    monkeypatch.setattr(registry_module, "build_web_search_tool", _build_web_search_tool)
    monkeypatch.setattr(registry_module, "load_mcp_tools", _load_mcp_tools)

    system_time_tool = _make_async_tool("get_system_time", "time")

    mcp_results: list[str] = []

    for _ in range(3):
        tools, meta_by_name = await registry_module.build_tool_registry_cached(
            settings=settings,
            extensions=[extension],
            extra_tools=[system_time_tool],
            include_web_search=True,
            include_web_extract=False,
            include_web_crawl=False,
            include_mcp=True,
            redis=redis,
            http_client=http_client,
        )
        assert [tool.name for tool in tools] == [
            "get_system_time",
            "web_search",
            registry_module.make_mcp_tool_name(str(extension.id), "echo"),
        ]
        assert set(meta_by_name) == {tool.name for tool in tools}
        mcp_results.append(await tools[-1].ainvoke({}))

    assert counts == {"web_search": 1, "mcp_load": 3}
    assert "mcp-1" in mcp_results[0]
    assert "mcp-2" in mcp_results[1]
    assert "mcp-3" in mcp_results[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_input_name", ["http_client", "redis"])
async def test_build_tool_registry_cached_invalidates_static_section_when_resource_identity_changes(
    monkeypatch: pytest.MonkeyPatch,
    cache_input_name: str,
) -> None:
    settings = _make_settings()
    counts = {"web_search": 0}

    monkeypatch.setattr(registry_module, "has_web_search_provider", lambda _s: True)
    monkeypatch.setattr(registry_module, "has_web_extract_provider", lambda _s: False)
    monkeypatch.setattr(registry_module, "has_jina_read_provider", lambda _s: False)

    def _build_web_search_tool(*_args, **_kwargs):
        counts["web_search"] += 1
        return _make_async_tool("web_search", "web")

    monkeypatch.setattr(registry_module, "build_web_search_tool", _build_web_search_tool)

    shared_http_client = object()
    shared_redis = object()
    first_kwargs = {
        "http_client": shared_http_client,
        "redis": shared_redis,
    }
    second_kwargs = dict(first_kwargs)
    second_kwargs[cache_input_name] = object()

    await registry_module.build_tool_registry_cached(
        settings=settings,
        include_web_search=True,
        include_mcp=False,
        **first_kwargs,
    )
    await registry_module.build_tool_registry_cached(
        settings=settings,
        include_web_search=True,
        include_mcp=False,
        **second_kwargs,
    )

    assert counts["web_search"] == 2


@pytest.mark.asyncio
async def test_build_tool_registry_cached_does_not_reuse_dynamic_extra_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings(mcp_enabled=False, web_search_api_key=None)

    monkeypatch.setattr(registry_module, "has_web_search_provider", lambda _s: False)
    monkeypatch.setattr(registry_module, "has_web_extract_provider", lambda _s: False)
    monkeypatch.setattr(registry_module, "has_jina_read_provider", lambda _s: False)

    tool_a = _make_async_tool("kb_retrieve", "first")
    tool_b = _make_async_tool("kb_retrieve", "second")

    tools_a, _ = await registry_module.build_tool_registry_cached(
        settings=settings,
        extra_tools=[tool_a],
        include_web_search=False,
        include_mcp=False,
    )
    tools_b, _ = await registry_module.build_tool_registry_cached(
        settings=settings,
        extra_tools=[tool_b],
        include_web_search=False,
        include_mcp=False,
    )

    assert tools_a == [tool_a]
    assert tools_b == [tool_b]
    assert tools_a[0] is tool_a
    assert tools_b[0] is tool_b


@pytest.mark.asyncio
async def test_build_tool_registry_cached_does_not_cache_runtime_mcp_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _make_settings()
    extension = _make_extension()

    monkeypatch.setattr(registry_module, "has_web_search_provider", lambda _s: False)
    monkeypatch.setattr(registry_module, "has_web_extract_provider", lambda _s: False)
    monkeypatch.setattr(registry_module, "has_jina_read_provider", lambda _s: False)

    async def _unexpected_load_mcp_tools(**_kwargs):  # noqa: ANN003
        raise AssertionError("runtime mcp_entries path should not call load_mcp_tools")

    monkeypatch.setattr(registry_module, "load_mcp_tools", _unexpected_load_mcp_tools)

    tools_a, _ = await registry_module.build_tool_registry_cached(
        settings=settings,
        extensions=[extension],
        mcp_entries=[
            SimpleNamespace(
                extension=extension,
                raw_tool_name="echo",
                tool=_make_async_tool("echo", "runtime-a"),
            )
        ],
        include_web_search=False,
        include_mcp=True,
    )
    tools_b, _ = await registry_module.build_tool_registry_cached(
        settings=settings,
        extensions=[extension],
        mcp_entries=[
            SimpleNamespace(
                extension=extension,
                raw_tool_name="echo",
                tool=_make_async_tool("echo", "runtime-b"),
            )
        ],
        include_web_search=False,
        include_mcp=True,
    )

    result_a = await tools_a[0].ainvoke({})
    result_b = await tools_b[0].ainvoke({})

    assert "runtime-a" in result_a
    assert "runtime-b" in result_b
