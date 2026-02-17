import pytest

from app.agents.kb_chat_agentic.schemas import HyDEBatchDecision
from app.services.query_rewrite_service import (
    HYDE_NUM_HYPOTHESES,
    QueryListResult,
    QueryRewriteService,
    StructuredCallResult,
    TextResult,
)


@pytest.mark.asyncio
async def test_hyde_prefers_structured_batch_output(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = QueryRewriteService()

    async def _fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=HyDEBatchDecision(
                hypothetical_documents=[
                    " 假设文档一 ",
                    "假设文档二",
                    "假设文档一",
                ]
            ),
            success=True,
            reason=None,
            latency_ms=1,
        )

    async def _fake_text(*args, **kwargs):  # type: ignore[no-untyped-def]
        return TextResult(text="", success=False, reason="should_not_call", latency_ms=0)

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)
    monkeypatch.setattr(svc, "_call_prompt_text", _fake_text)

    result = await svc.hyde("测试问题", enabled=True)

    assert isinstance(result, QueryListResult)
    assert result.success is True
    assert result.reason == "llm_structured"
    assert result.queries == ["假设文档一", "假设文档二"]


@pytest.mark.asyncio
async def test_hyde_falls_back_to_text_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = QueryRewriteService()

    async def _fake_structured(*args, **kwargs):  # type: ignore[no-untyped-def]
        return StructuredCallResult(
            payload=None,
            success=False,
            reason="invalid_schema",
            latency_ms=1,
        )

    async def _fake_text(*args, **kwargs):  # type: ignore[no-untyped-def]
        return TextResult(
            text="\n".join(f"{idx}. 假设文档{idx}" for idx in range(1, HYDE_NUM_HYPOTHESES + 2)),
            success=True,
            reason=None,
            latency_ms=1,
        )

    monkeypatch.setattr(svc, "_call_prompt_structured", _fake_structured)
    monkeypatch.setattr(svc, "_call_prompt_text", _fake_text)

    result = await svc.hyde("测试问题", enabled=True)

    assert result.success is True
    assert result.reason == "llm_text_fallback"
    assert len(result.queries) == HYDE_NUM_HYPOTHESES
