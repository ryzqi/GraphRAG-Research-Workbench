from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.kb_chat_agentic import preprocess


class _FakeStoreManager:
    @classmethod
    def status(cls) -> dict[str, object]:
        return {
            "status": "degraded",
            "configured_backend": "postgres",
            "effective_backend": "memory",
            "degraded": True,
            "reason": "persistent_store_unavailable",
        }


@pytest.mark.asyncio
async def test_complexity_cache_marks_degraded_inmemory_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_read_complexity_cache(**kwargs) -> dict[str, object]:
        del kwargs
        return {
            "strategy": "multi_query",
            "success": True,
            "reasoning": "cached",
            "confidence": 0.81,
            "risk_flags": ["comparison"],
            "decision_version": "cached-v1",
        }

    monkeypatch.setattr(preprocess, "_read_complexity_cache", _fake_read_complexity_cache)
    monkeypatch.setattr(preprocess, "StoreManager", _FakeStoreManager, raising=False)

    decision = await preprocess._classify_query_strategy(
        state={
            "user_input": "比较一下 A 和 B",
            "normalized_meta": {
                "recall_risk": "low",
                "has_multi_target": True,
                "is_comparison": True,
            },
        },
        settings=SimpleNamespace(
            kb_chat_complexity_cache_enabled=True,
        ),
        runtime=SimpleNamespace(store=object(), context={}),
    )

    assert decision["cache_hit"] is True
    assert decision["cache_status"] == "degraded_inmemory_store"
