from __future__ import annotations

import pytest
from langchain.messages import AIMessage

import app.services.query_rewrite_service as query_rewrite_service_module
from app.agents.kb_chat_agentic.schemas import (
    AmbiguityDecision,
    ComplexityDecision,
    ContextCompressDecision,
    ContextCompressItem,
    DecompositionDecision,
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
async def test_invoke_model_structured_disables_responses_api_replay_for_compat_provider() -> None:
    payload = AmbiguityDecision(
        ambiguous=False,
        reason_code="mixed",
        confidence=0.18,
        reasoning="可直接继续。",
        clarifying_question="",
        missing_slots=[],
        suggested_answers=[],
    )
    fake_model = _FakeChatModel(payload)
    captured: dict[str, object] = {}
    original_factory = query_rewrite_service_module.create_chat_model

    def _fake_create_chat_model(*, settings: object = None, use_previous_response_id: object = None) -> object:
        captured["settings"] = settings
        captured["use_previous_response_id"] = use_previous_response_id
        return fake_model

    query_rewrite_service_module.create_chat_model = _fake_create_chat_model  # type: ignore[assignment]
    try:
        service = QueryRewriteService()
        result = await service._invoke_model_structured(
            schema=AmbiguityDecision,
            user_prompt="请判断是否存在歧义",
            max_tokens=96,
        )
    finally:
        query_rewrite_service_module.create_chat_model = original_factory  # type: ignore[assignment]

    assert result.success is True
    assert captured["use_previous_response_id"] is False


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
        (AmbiguityDecision, {"method": "function_calling", "include_raw": True})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1


@pytest.mark.asyncio
async def test_call_prompt_structured_uses_model_function_calling_path() -> None:
    class _StubPromptLoader:
        def render_with_few_shot(self, prompt_key: str, **kwargs: object) -> str:
            assert prompt_key == "kb_chat/decomposition"
            assert kwargs["question"] == "说明 CoT 和 ToT 的区别"
            return "rendered decomposition prompt"

    service = QueryRewriteService()
    service._prompts = _StubPromptLoader()  # type: ignore[assignment]

    async def _fake_invoke_model_structured(
        *,
        schema: type[object],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        assert schema is DecompositionDecision
        assert user_prompt == "rendered decomposition prompt"
        assert max_tokens == 256
        return StructuredCallResult(
            payload=DecompositionDecision(
                strategy="decomposition",
                plan_version="kb_chat_decomposition_plan_v2",
                sub_queries=["CoT 工作机制", "ToT 工作机制"],
                sub_query_specs=[
                    {
                        "query": "CoT 工作机制",
                        "purpose": "提取 CoT 机制",
                        "priority": 1,
                        "coverage_tags": ["entity", "process"],
                    },
                    {
                        "query": "ToT 工作机制",
                        "purpose": "提取 ToT 机制",
                        "priority": 1,
                        "coverage_tags": ["entity", "process"],
                    },
                ],
                risk_flags=[],
                reasoning="按两个框架分别取证。",
            ),
            success=True,
            reason="ok",
            latency_ms=12,
        )

    service._invoke_model_structured = _fake_invoke_model_structured  # type: ignore[method-assign]
    service._get_structured_agent = lambda schema: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("不应再走 legacy create_agent structured path")
    )

    result = await service._call_prompt_structured(
        "kb_chat/decomposition",
        schema=DecompositionDecision,
        max_tokens=256,
        question="说明 CoT 和 ToT 的区别",
    )

    assert result.success is True
    assert isinstance(result.payload, DecompositionDecision)
    assert result.reason == "ok"


@pytest.mark.asyncio
async def test_invoke_model_structured_parses_raw_json_content_when_provider_skips_tool_call() -> None:
    raw_message = AIMessage(
        content='{"reasoning":"这是比较问题，需要拆解检索。","strategy":"decomposition","confidence":0.97,"risk_flags":["comparison","multi_target"],"decision_version":"kb_chat_complexity_classify_v5"}'
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})
    service = QueryRewriteService()
    service._structured_chat_model = fake_model

    result = await service._invoke_model_structured(
        schema=ComplexityDecision,
        user_prompt="请判断当前问题的检索复杂度",
        max_tokens=192,
    )

    assert result.success is True
    assert isinstance(result.payload, ComplexityDecision)
    assert result.payload.strategy == "decomposition"
    assert result.payload.risk_flags == ["comparison", "multi_target"]
    assert fake_model.structured_calls == [
        (ComplexityDecision, {"method": "function_calling", "include_raw": True})
    ]


@pytest.mark.asyncio
async def test_invoke_model_structured_parses_raw_tool_call_args_when_parser_returns_none() -> None:
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "ComplexityDecision",
                "args": {
                    "reasoning": "这是比较问题，需要拆解检索。",
                    "strategy": "decomposition",
                    "confidence": 0.97,
                    "risk_flags": ["comparison", "multi_target"],
                    "decision_version": "kb_chat_complexity_classify_v5",
                },
                "id": "chatcmpl-tool-1",
                "type": "tool_call",
            }
        ],
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})
    service = QueryRewriteService()
    service._structured_chat_model = fake_model

    result = await service._invoke_model_structured(
        schema=ComplexityDecision,
        user_prompt="请判断当前问题的检索复杂度",
        max_tokens=192,
    )

    assert result.success is True
    assert isinstance(result.payload, ComplexityDecision)
    assert result.payload.strategy == "decomposition"
    assert result.payload.risk_flags == ["comparison", "multi_target"]
    assert fake_model.structured_calls == [
        (ComplexityDecision, {"method": "function_calling", "include_raw": True})
    ]


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
        (ContextCompressDecision, {"method": "function_calling", "include_raw": True})
    ]
    assert fake_model.structured_runnable is not None
    assert len(fake_model.structured_runnable.requests) == 1


@pytest.mark.asyncio
async def test_compress_context_parses_raw_json_content_when_provider_returns_plain_json() -> None:
    raw_message = AIMessage(
        content='{"decision":"subset","items":[{"citation_id":"S1","excerpt":"原文证据一：答案是甲。"}]}'
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})

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

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["final_context"] == "[S1] 原文证据一：答案是甲。"
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]
    assert fake_model.structured_calls == [
        (ContextCompressDecision, {"method": "function_calling", "include_raw": True})
    ]


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
    query = "比较 Agentic AI 和传统大语言模型（LLM）的核心区别，并说明 Agentic AI 的四大核心组件如何支撑这种差异。"

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

    result = await service.decompose(query)

    assert result.success is False
    assert result.reason == "error"
    assert len(result.queries) >= 2
    assert result.plan["strategy"] == "decomposition"
    assert "comparison" in result.plan["risk_flags"]
    assert result.diagnostics["source"] == "heuristic_decomposition"


@pytest.mark.asyncio
async def test_decompose_uses_rule_based_subqueries_when_structured_output_is_insufficient() -> None:
    service = QueryRewriteService()
    query = "说明 CoT 和 ToT 的区别"

    async def _insufficient_prompt_call(
        prompt_key: str,
        *,
        schema: type[object],
        max_tokens: int,
        **kwargs: object,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/decomposition"
        assert schema is DecompositionDecision
        assert max_tokens == 256
        assert kwargs["question"] == query
        return StructuredCallResult(
            payload=DecompositionDecision(
                strategy="decomposition",
                plan_version="kb_chat_decomposition_plan_v2",
                sub_queries=["CoT 工作机制 核心特点"],
                sub_query_specs=[
                    {
                        "query": "CoT 工作机制 核心特点",
                        "purpose": "只返回了单条，触发 fail-open",
                        "priority": 1,
                        "coverage_tags": ["entity", "process"],
                    }
                ],
                risk_flags=["compare"],
                reasoning="输出不足两条",
            ),
            success=True,
            reason="ok",
            latency_ms=18,
        )

    service._call_prompt_structured = _insufficient_prompt_call  # type: ignore[method-assign]

    result = await service.decompose(query)

    assert result.success is False
    assert result.reason == "llm_invalid_decomposition_insufficient_subqueries"
    assert len(result.queries) >= 2
    assert result.plan["strategy"] == "decomposition"
    assert "comparison" in result.plan["risk_flags"]
    assert result.diagnostics["source"] == "heuristic_decomposition"
