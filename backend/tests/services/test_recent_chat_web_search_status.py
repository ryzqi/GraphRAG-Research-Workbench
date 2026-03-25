from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.api.v1.endpoints.chats as chats_module


class _FakeResult:
    def all(self) -> list[tuple[object, object, object]]:
        return []


class _FakeDb:
    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult()


@pytest.mark.asyncio
async def test_list_recent_chats_returns_structured_web_search_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chats_module,
        "get_settings",
        lambda: SimpleNamespace(web_search_api_key="configured-key"),
    )

    async def _fake_get_web_search_status(*, settings: object) -> dict[str, object]:
        assert settings is not None
        return {
            "configured": True,
            "verified": True,
            "healthy": True,
        }

    monkeypatch.setattr(
        chats_module,
        "get_web_search_status",
        _fake_get_web_search_status,
        raising=False,
    )

    result = await chats_module.list_recent_chats(db=_FakeDb(), limit=20)

    assert result.model_dump() == {
        "items": [],
        "web_search": {
            "configured": True,
            "verified": True,
            "healthy": True,
        },
    }
