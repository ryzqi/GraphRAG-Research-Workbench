from __future__ import annotations

import pytest

from app.agents.kb_chat_agentic import preprocess
from app.core.settings import Settings
from app.services.query_rewrite_service import QueryListResult, TextResult


@pytest.mark.asyncio
async def test_decomposition_stage_summary_marks_llm_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    state = {
        "normalized_query": "test query",
        "runtime_config": {"decomposition_enabled": True},
    }

    async def fake_decompose(self, query: str, *, enabled: bool | None = None, max_sub_questions: int | None = None):  # type: ignore[no-untyped-def]
        return QueryListResult(
            queries=["sub-1", "sub-2"],
            success=True,
            reason="llm_structured",
            latency_ms=4,
        )

    monkeypatch.setattr("app.services.query_rewrite_service.QueryRewriteService.decompose", fake_decompose)

    result = await preprocess.decomposition(state, settings)

    assert result["sub_queries"] == ["sub-1", "sub-2"]
    stage = result["stage_summaries"]["decomposition"]
    assert stage["driver"] == "llm"
    assert stage["success"] is True
    assert stage["reason"] == "llm_structured"


@pytest.mark.asyncio
async def test_hyde_stage_summary_marks_llm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    state = {
        "normalized_query": "test query",
        "runtime_config": {"hyde_enabled": True},
    }

    async def fake_hyde(self, query: str, *, enabled: bool | None = None):  # type: ignore[no-untyped-def]
        return TextResult(
            text="",
            success=False,
            reason="llm_failed_fallback_empty",
            latency_ms=7,
        )

    monkeypatch.setattr("app.services.query_rewrite_service.QueryRewriteService.hyde", fake_hyde)

    result = await preprocess.hyde(state, settings)

    assert result["hyde_doc"] == ""
    stage = result["stage_summaries"]["hyde"]
    assert stage["driver"] == "llm"
    assert stage["success"] is False
    assert stage["reason"] == "llm_failed_fallback_empty"
