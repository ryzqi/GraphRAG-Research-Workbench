from __future__ import annotations

import pytest

from app.agents.kb_chat_agentic.schemas import (
    AmbiguityDecision,
    ComplexityDecision,
    ContextCompressDecision,
    ContextCompressItem,
)
from app.agents.retrieval_subgraph import _compress_context
from app.services.query_rewrite_service import QueryRewriteService, StructuredCallResult


class _FakeStructuredRunnable:
    def __init__(self, response: object) -> None:
        self._response = response
        self.requests: list[object] = []

    async def ainvoke(self, request: object) -> object:
        self.requests.append(request)
        return self._response


class _FakeChatModel:
    def __init__(self, response: object) -> None:
        self._response = response
        self.bound_kwargs: dict[str, object] | None = None
        self.structured_calls: list[tuple[object, dict[str, object]]] = []
        self.structured_runnable: _FakeStructuredRunnable | None = None

    def bind(self, **kwargs: object) -> "_FakeChatModel":
        self.bound_kwargs = kwargs
        return self

    def with_structured_output(
        self, schema: object, /, **kwargs: object
    ) -> _FakeStructuredRunnable:
        self.structured_calls.append((schema, kwargs))
        self.structured_runnable = _FakeStructuredRunnable(self._response)
        return self.structured_runnable


@pytest.mark.asyncio
async def test_invoke_model_structured_accepts_direct_pydantic_payload_and_uses_function_calling() -> None:
    payload = AmbiguityDecision(
        ambiguous=True,
        reason_code="mixed",
        confidence=0.82,
        reasoning="需要用户补充范围。",
        clarifying_question="请说明你要查的范围。",
        missing_slots=[],
        suggested_answers=[],
    )
    fake_model = _FakeChatModel(payload)
    service = QueryRewriteService()
    service._structured_chat_model = fake_model

    result = await service._invoke_model_structured(
        schema=AmbiguityDecision,
        user_prompt="请判断是否存在歧义",
        max_tokens=128,
    )

    assert result.success is True
    assert result.payload == payload
    assert fake_model.bound_kwargs == {"max_tokens": 128}
    assert fake_model.structured_calls == [
        (AmbiguityDecision, {"method": "function_calling"})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1


@pytest.mark.asyncio
async def test_compress_context_accepts_direct_pydantic_payload_and_uses_function_calling() -> None:
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt="原文证据一：答案是甲。",
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "答案是什么？",
            "evidence_items": [
                {"citation_id": "S1", "excerpt": "原文证据一：答案是甲。"},
                {"citation_id": "S2", "excerpt": "原文证据二：答案是乙。"},
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["final_context"] == "[S1] 原文证据一：答案是甲。"
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]
    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["selected_citation_ids"] == ["S1"]
    assert fake_model.structured_calls == [
        (ContextCompressDecision, {"method": "function_calling"})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1


@pytest.mark.asyncio
async def test_classify_complexity_uses_multi_query_heuristic_when_structured_call_fails() -> None:
    service = QueryRewriteService()

    async def _failing_structured_call(
        *,
        schema: type[ComplexityDecision],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        assert schema is ComplexityDecision
        assert "Tool Use / Function Calling" in user_prompt
        assert max_tokens == 256
        return StructuredCallResult(
            payload=None,
            success=False,
            reason="error",
            latency_ms=12,
        )

    service._invoke_model_structured = _failing_structured_call  # type: ignore[method-assign]

    result = await service.classify_complexity(
        "AI Agent 的 Tool Use / Function Calling 六步完整流程是什么？",
        recall_risk="medium",
        has_multi_target=False,
        is_comparison=False,
    )

    assert result.success is False
    assert result.strategy == "multi_query"
    assert result.failure_reason == "error"
    assert "term_alias" in result.risk_flags


@pytest.mark.asyncio
async def test_classify_complexity_uses_decomposition_heuristic_for_compare_and_explain_query_when_structured_call_fails() -> None:
    service = QueryRewriteService()

    async def _failing_structured_call(
        *,
        schema: type[ComplexityDecision],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        assert schema is ComplexityDecision
        assert "比较 Agentic AI 和传统大语言模型" in user_prompt
        assert max_tokens == 256
        return StructuredCallResult(
            payload=None,
            success=False,
            reason="error",
            latency_ms=9,
        )

    service._invoke_model_structured = _failing_structured_call  # type: ignore[method-assign]

    result = await service.classify_complexity(
        "比较 Agentic AI 和传统大语言模型（LLM）的核心区别，并说明 Agentic AI 的四大核心组件如何支撑这种差异。",
        recall_risk="medium",
        has_multi_target=False,
        is_comparison=False,
    )

    assert result.success is False
    assert result.strategy == "decomposition"
    assert result.failure_reason == "error"
    assert "comparison" in result.risk_flags


@pytest.mark.asyncio
async def test_decompose_uses_rule_based_subqueries_when_structured_call_fails() -> None:
    service = QueryRewriteService()

    async def _failing_prompt_call(
        prompt_key: str,
        *,
        schema: type[object],
        max_tokens: int,
        **kwargs: object,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/decomposition"
        assert schema.__name__ == "DecompositionDecision"
        assert max_tokens == 256
        assert "比较 Agentic AI 和传统大语言模型" in str(kwargs["question"])
        return StructuredCallResult(
            payload=None,
            success=False,
            reason="error",
            latency_ms=15,
        )

    service._call_prompt_structured = _failing_prompt_call  # type: ignore[method-assign]

    result = await service.decompose(
        "比较 Agentic AI 和传统大语言模型（LLM）的核心区别，并说明 Agentic AI 的四大核心组件如何支撑这种差异。"
    )

    assert result.success is False
    assert result.reason == "error"
    assert len(result.queries) >= 2
    assert result.plan["strategy"] == "decomposition"
    assert "comparison" in result.plan["risk_flags"]
    assert result.diagnostics["source"] == "heuristic_decomposition"
