from __future__ import annotations

import pytest

from app.services.query_rewrite_service import QueryRewriteService


async def _unexpected_rewrite(*args, **kwargs):  # pragma: no cover - guard helper
    raise AssertionError("rewrite() should not be called when transform is disabled")


@pytest.mark.asyncio
async def test_transform_query_skips_fallback_rewrite_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QueryRewriteService()
    monkeypatch.setattr(service, "rewrite", _unexpected_rewrite)

    result = await service.transform_query(
        "测试问题",
        reason="retry",
        enabled=False,
    )

    assert result.query == "测试问题"
    assert result.rewritten is False
    assert result.reason == "disabled"
