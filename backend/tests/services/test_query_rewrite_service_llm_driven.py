from __future__ import annotations

import pytest

from app.agents.kb_chat_agentic.schemas import (
    DecompositionDecision,
    HyDEDecision,
    MultiQueryDecision,
)
from app.core.settings import Settings
from app.services.query_rewrite_service import (
    QueryRewriteService,
    StructuredCallResult,
    TextResult,
)


@pytest.mark.asyncio
async def test_decompose_prefers_structured_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    service = QueryRewriteService(settings=Settings())

    async def fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=DecompositionDecision(sub_queries=["alpha", "beta"]),
            success=True,
            reason=None,
            latency_ms=3,
        )

    monkeypatch.setattr(service, "_call_prompt_structured", fake_structured)

    result = await service.decompose("ignored", enabled=True)

    assert result.success is True
    assert result.reason == "llm_structured"
    assert result.queries == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_generate_variants_uses_text_fallback_when_structured_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QueryRewriteService(settings=Settings())

    async def fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=None,
            success=False,
            reason="invalid_schema",
            latency_ms=7,
        )

    async def fake_text(*args, **kwargs):  # type: ignore[no-untyped-def]
        return TextResult(
            text="- gamma\n- delta\n- gamma",
            success=True,
            reason=None,
            latency_ms=9,
        )

    monkeypatch.setattr(service, "_call_prompt_structured", fake_structured)
    monkeypatch.setattr(service, "_call_prompt_text", fake_text)

    result = await service.generate_variants("ignored", enabled=True)

    assert result.success is True
    assert result.reason == "llm_text_fallback"
    assert result.queries == ["gamma", "delta"]


@pytest.mark.asyncio
async def test_hyde_returns_empty_when_all_llm_paths_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QueryRewriteService(settings=Settings())

    async def fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=None,
            success=False,
            reason="timeout",
            latency_ms=20,
        )

    async def fake_text(*args, **kwargs):  # type: ignore[no-untyped-def]
        return TextResult(
            text="",
            success=False,
            reason="timeout",
            latency_ms=21,
        )

    monkeypatch.setattr(service, "_call_prompt_structured", fake_structured)
    monkeypatch.setattr(service, "_call_prompt_text", fake_text)

    result = await service.hyde("ignored", enabled=True)

    assert result.success is False
    assert result.reason == "llm_failed_fallback_empty"
    assert result.text == ""


@pytest.mark.asyncio
async def test_hyde_prefers_structured_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    service = QueryRewriteService(settings=Settings())

    async def fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=HyDEDecision(hypothetical_document="hypo doc"),
            success=True,
            reason=None,
            latency_ms=5,
        )

    monkeypatch.setattr(service, "_call_prompt_structured", fake_structured)

    result = await service.hyde("ignored", enabled=True)

    assert result.success is True
    assert result.reason == "llm_structured"
    assert result.text == "hypo doc"


@pytest.mark.asyncio
async def test_generate_variants_prefers_structured_llm_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = QueryRewriteService(settings=Settings())

    async def fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=MultiQueryDecision(queries=["q1", "q2"]),
            success=True,
            reason=None,
            latency_ms=2,
        )

    monkeypatch.setattr(service, "_call_prompt_structured", fake_structured)

    result = await service.generate_variants("ignored", enabled=True)

    assert result.success is True
    assert result.reason == "llm_structured"
    assert result.queries == ["q1", "q2"]
