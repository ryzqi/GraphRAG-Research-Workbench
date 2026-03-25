from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.general_chat_service as general_chat_service_module
from app.services.general_chat_service import GeneralChatService


@pytest.mark.asyncio
async def test_load_tool_registry_for_general_chat_enables_web_extract_with_web_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = GeneralChatService.__new__(GeneralChatService)
    service._settings = SimpleNamespace(mcp_enabled=False, web_search_api_key="test-key")
    service._db = None
    service._redis = None
    service._http_client = None

    captured: dict[str, object] = {}

    async def _fake_build_tool_registry(**kwargs: object):
        captured.update(kwargs)
        return [], {}

    monkeypatch.setattr(
        general_chat_service_module,
        "build_tool_registry",
        _fake_build_tool_registry,
    )

    await service._load_tool_registry_for_session(
        session=SimpleNamespace(allow_external=False)
    )

    assert captured["include_web_search"] is True
    assert captured["include_web_extract"] is True
    assert captured["include_mcp"] is False
