from __future__ import annotations

import pytest
from langchain.messages import AIMessage
from types import SimpleNamespace

import app.agents.kb_chat_agentic.preprocess as preprocess_module
import app.agents.kb_chat_agentic.reflection as reflection_module
import app.services.query_rewrite_service as query_rewrite_service_module
from app.agents.kb_chat_agentic.schemas import (
    AmbiguityDecision,
    ComplexityDecision,
    ContextCompressDecision,
    ContextCompressItem,
    DecompositionDecision,
    MultiQueryDecision,
    NormalizeDecision,
    TransformQueryDecision,
)
from app.agents.retrieval_subgraph import (
    _compress_context,
    _is_verbatim_subset,
    _retrieval_plan_node,
)
from app.services.query_rewrite_service import (
    QueryRewriteService,
    RetrievalPlanResult,
    RewriteResult,
    StructuredCallResult,
)


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
async def test_call_prompt_structured_retries_once_after_retryable_structured_failure() -> None:
    class _StubPromptLoader:
        def render_with_few_shot(self, prompt_key: str, **kwargs: object) -> str:
            assert prompt_key == "kb_chat/normalize_query"
            assert kwargs["question"] == "AI Agent 的六大核心组件是什么？"
            return "rendered normalize prompt"

    service = QueryRewriteService()
    service._prompts = _StubPromptLoader()  # type: ignore[assignment]
    attempts: list[int] = []

    async def _fake_invoke_model_structured(
        *,
        schema: type[object],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        assert schema is NormalizeDecision
        assert user_prompt == "rendered normalize prompt"
        assert max_tokens == 320
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            return StructuredCallResult(
                payload=None,
                success=False,
                reason="empty_structured_response",
            )
        return StructuredCallResult(
            payload=NormalizeDecision(
                canonical_query="AI Agent 的六大核心组件是什么？",
                aliases=["AI Agent"],
                entities=["AI Agent"],
                time_constraints=[],
                metric_constraints=[],
                scope_constraints=[],
                recall_risk="low",
                drift_risk=False,
                constraint_preserved=True,
                has_multi_target=False,
                is_comparison=False,
                reasoning="重试后拿到结构化结果。",
            ),
            success=True,
            reason=None,
        )

    service._invoke_model_structured = _fake_invoke_model_structured  # type: ignore[method-assign]

    result = await service._call_prompt_structured(
        "kb_chat/normalize_query",
        schema=NormalizeDecision,
        max_tokens=320,
        question="AI Agent 的六大核心组件是什么？",
    )

    assert result.success is True
    assert isinstance(result.payload, NormalizeDecision)
    assert attempts == [1, 2]


@pytest.mark.asyncio
async def test_generate_variants_replaces_taxonomy_intent_drift_queries_with_rule_completion() -> None:
    service = QueryRewriteService()
    original_query = "Chain-of-Thought（CoT，思维链）的主要变体有哪些？"

    async def _prompt_returns_bad_taxonomy_queries(
        prompt_key: str,
        *,
        schema: type[object],
        max_tokens: int,
        **kwargs: object,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/multi_query"
        assert schema is MultiQueryDecision
        assert max_tokens == 256
        assert kwargs["question"] == original_query
        return StructuredCallResult(
            payload=MultiQueryDecision(
                queries=[
                    "Chain-of-Thought 变体 术语 分类",
                    "Chain-of-Thought 在数学解题 场景 应用",
                    "Chain-of-Thought 变体 性能 对比 优缺点",
                ]
            ),
            success=True,
            reason="ok",
            latency_ms=11,
        )

    service._call_prompt_structured = _prompt_returns_bad_taxonomy_queries  # type: ignore[method-assign]

    result = await service.generate_variants(original_query)

    assert len(result.queries) == 3
    assert any("主要变体" in query or "类型 分类" in query for query in result.queries)
    assert all("数学解题" not in query for query in result.queries)
    assert all("性能 对比 优缺点" not in query for query in result.queries)


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
async def test_invoke_model_structured_parses_raw_normalize_tool_call_args_with_long_reasoning() -> None:
    long_reasoning = "Embedding 与 Re-rank 需要分别覆盖职责、架构与挑战。" * 12
    assert len(long_reasoning) > 240
    payload = {
        "canonical_query": "Embedding model responsibilities, architecture, challenges; Re-rank model responsibilities, architecture, challenges",
        "aliases": [],
        "entities": ["Embedding model", "Re-rank model"],
        "time_constraints": [],
        "metric_constraints": [],
        "scope_constraints": [],
        "recall_risk": "medium",
        "drift_risk": False,
        "constraint_preserved": True,
        "has_multi_target": True,
        "is_comparison": False,
        "reasoning": long_reasoning,
    }
    try:
        NormalizeDecision.model_validate(payload)
    except Exception as exc:
        parsing_error = exc
    else:  # pragma: no cover - 当前上限若已放宽，这里不应走到红灯阶段
        parsing_error = None

    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "NormalizeDecision",
                "args": payload,
                "id": "chatcmpl-tool-normalize-1",
                "type": "tool_call",
            }
        ],
    )
    fake_model = _FakeChatModel(
        {"raw": raw_message, "parsed": None, "parsing_error": parsing_error}
    )
    service = QueryRewriteService()
    service._structured_chat_model = fake_model

    result = await service._invoke_model_structured(
        schema=NormalizeDecision,
        user_prompt="请规范化检索查询",
        max_tokens=320,
    )

    assert result.success is True
    assert isinstance(result.payload, NormalizeDecision)
    assert result.payload.has_multi_target is True
    assert result.payload.entities == ["Embedding model", "Re-rank model"]
    assert result.payload.reasoning == long_reasoning
    assert fake_model.structured_calls == [
        (NormalizeDecision, {"method": "function_calling", "include_raw": True})
    ]


@pytest.mark.asyncio
async def test_invoke_model_structured_reports_invalid_schema_for_raw_tool_call_args_without_parsing_error() -> None:
    raw_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "NormalizeDecision",
                "args": {
                    "canonical_query": "AI Agent 六大核心组件是什么？",
                    "aliases": [],
                    "entities": [],
                    "time_constraints": [],
                    "metric_constraints": [],
                    "scope_constraints": [],
                    "recall_risk": "unknown",
                    "drift_risk": False,
                    "constraint_preserved": True,
                    "has_multi_target": False,
                    "is_comparison": False,
                    "reasoning": "故意构造非法 recall_risk。",
                },
                "id": "chatcmpl-tool-normalize-2",
                "type": "tool_call",
            }
        ],
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})
    service = QueryRewriteService()
    service._structured_chat_model = fake_model

    result = await service._invoke_model_structured(
        schema=NormalizeDecision,
        user_prompt="请规范化检索查询",
        max_tokens=320,
    )

    assert result.success is False
    assert result.reason == "invalid_schema"
    assert fake_model.structured_calls == [
        (NormalizeDecision, {"method": "function_calling", "include_raw": True})
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
async def test_compress_context_repairs_malformed_raw_json_with_quoted_object_items() -> None:
    raw_message = AIMessage(
        content=(
            '{"decision":"subset","items":['
            '{"citation_id":"S1","excerpt":"原文证据一：答案是甲。"},'
            '"{"citation_id":"S2","excerpt":"原文证据二：答案是乙。"}'
            ']}'
        )
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
    assert result["compression_stats"]["selected_citation_ids"] == ["S1", "S2"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1", "S2"]
    assert result["final_context"] == "[S1] 原文证据一：答案是甲。\n\n[S2] 原文证据二：答案是乙。"


@pytest.mark.asyncio
async def test_compress_context_repairs_malformed_raw_json_when_array_item_loses_opening_brace() -> None:
    raw_message = AIMessage(
        content=(
            '{"decision":"subset","items":['
            '{"citation_id":"S1","excerpt":"原文证据一：答案是甲。"},'
            '"citation_id":"S2","excerpt":"原文证据二：答案是乙。"}'
            ']}'
        )
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})

    result = await _compress_context(
        state={
            "user_input": "答案分别是什么？",
            "evidence_items": [
                {"citation_id": "S1", "excerpt": "原文证据一：答案是甲。"},
                {"citation_id": "S2", "excerpt": "原文证据二：答案是乙。"},
                {"citation_id": "S3", "excerpt": "原文证据三：答案是丙。"},
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["selected_citation_ids"] == ["S1", "S2"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1", "S2"]
    assert result["final_context"] == "[S1] 原文证据一：答案是甲。\n\n[S2] 原文证据二：答案是乙。"


@pytest.mark.asyncio
async def test_compress_context_repairs_live_round18_object_separator_drift() -> None:
    raw_message = AIMessage(
        content=(
            '{"decision":"subset","items":['
            '{"citation_id":"S1","excerpt":"1. **海选阶段 (召回 Recall)**：由 **Embedding模型** 负责，像一个高效的“猎人”，'
            '快速从海量信息中捕获所有可能相关的候选项。 2. **决赛阶段 (排序 Ranking)**：由 **Re-rank模型** 负责，'
            '像一个严格的“裁判”，对海选出的候选项进行精细化打分和排序，将最"},"},'
            '{"citation_id":"S2","excerpt":"- **技术架构：双塔结构 (Dual-Encoder)**\\n'
            '    - 一个“塔”专门编码用户查询 (Query)。\\n'
            '    - 另一个“塔”专门编码所有商品或内容 (Item)。\\n'
            '- **面临的挑战：向量表达的对齐与冷启动**\\n'
            '    - **对齐**：如何训练模型，使其产出的向量能够真正代表用户的意图和物品的特性。\\n'
            '    - **冷启动**：对于没有历史点击数据的新商品，模型难以准确生成其向量。"},"},'
            '{"citation_id":"S4","excerpt":"- **技术架构：交叉编码器 (Cross-Encoder)**\\n'
            '    - 将“用户查询”和“单个候选项”**作为一个整体**输入到模型中，进行深度的语义交互和匹配分析。\\n'
            '- **面临的挑战：算力与性能的平衡**\\n'
            '    - 如何在保证排序效果（复杂建模）与维持系统实时响应之间找到最佳平衡点。"}]}'
        )
    )
    fake_model = _FakeChatModel({"raw": raw_message, "parsed": None, "parsing_error": None})

    result = await _compress_context(
        state={
            "user_input": "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？",
            "evidence_items": [
                {
                    "citation_id": "S1",
                    "excerpt": "1. **海选阶段 (召回 Recall)**：由 **Embedding模型** 负责，像一个高效的“猎人”，快速从海量信息中捕获所有可能相关的候选项。 2. **决赛阶段 (排序 Ranking)**：由 **Re-rank模型** 负责，像一个严格的“裁判”，对海选出的候选项进行精细化打分和排序，将最",
                },
                {
                    "citation_id": "S2",
                    "excerpt": "- **技术架构：双塔结构 (Dual-Encoder)**\n    - 一个“塔”专门编码用户查询 (Query)。\n    - 另一个“塔”专门编码所有商品或内容 (Item)。\n- **面临的挑战：向量表达的对齐与冷启动**\n    - **对齐**：如何训练模型，使其产出的向量能够真正代表用户的意图和物品的特性。\n    - **冷启动**：对于没有历史点击数据的新商品，模型难以准确生成其向量。",
                },
                {
                    "citation_id": "S4",
                    "excerpt": "- **技术架构：交叉编码器 (Cross-Encoder)**\n    - 将“用户查询”和“单个候选项”**作为一个整体**输入到模型中，进行深度的语义交互和匹配分析。\n- **面临的挑战：算力与性能的平衡**\n    - 如何在保证排序效果（复杂建模）与维持系统实时响应之间找到最佳平衡点。",
                },
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["selected_citation_ids"] == ["S1", "S2", "S4"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1", "S2", "S4"]


@pytest.mark.asyncio
async def test_compress_context_collapses_duplicate_fragments_from_same_citation_to_source_excerpt() -> None:
    source_excerpt = (
        "AI Agent 的六大核心组件包括：\n"
        "### 感知 (Perception)\n"
        "1.  **功能**：作为 Agent 的“五官”，负责从外部世界获取信息。\n"
        "### 记忆 (Memory)\n"
        "1.  **功能**：存储信息，确保任务的连续性和个性化，避免“一锤子买卖”。\n"
        "### 规划 (Planning)\n"
        "1.  **功能**：制定完成任务的“作战计划”，是 Agent 的“策略中心”。\n"
        "### 推理引擎 (Reasoning Engine)\n"
        "1.  **功能**：作为 Agent 的“大脑”，通常由大语言模型（LLM）担任。\n"
        "### 工具使用 (Tool Use)\n"
        "1.  **功能**：让 Agent 能够借助外部工具来完成自身无法独立完成的任务。\n"
        "### 行动 (Action)\n"
        "1.  **功能**：根据规划和推理的结果，执行具体的操作。"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt='感知 (Perception)\n1.  **功能**：作为 Agent 的“五官”，负责从外部世界获取信息。',
            ),
            ContextCompressItem(
                citation_id="S1",
                excerpt='记忆 (Memory)\n1.  **功能**：存储信息，确保任务的连续性和个性化，避免“一锤子买卖”。',
            ),
            ContextCompressItem(
                citation_id="S1",
                excerpt='规划 (Planning)\n1.  **功能**：制定完成任务的“作战计划”，是 Agent 的“策略中心”。',
            ),
            ContextCompressItem(
                citation_id="S1",
                excerpt='推理引擎 (Reasoning Engine)\n1.  **功能**：作为 Agent 的“大脑”，通常由大语言模型（LLM）担任。',
            ),
            ContextCompressItem(
                citation_id="S1",
                excerpt="工具使用 (Tool Use)\n1.  **功能**：让 Agent 能够借助外部工具来完成自身无法独立完成的任务。",
            ),
            ContextCompressItem(
                citation_id="S1",
                excerpt="行动 (Action)\n1.  **功能**：根据规划和推理的结果，执行具体的操作。",
            ),
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "AI Agent 的六大核心组件是什么？",
            "evidence_items": [
                {"citation_id": "S1", "excerpt": source_excerpt},
                {
                    "citation_id": "S2",
                    "excerpt": "AI Agent 的核心优势在于类人的端到端任务处理流程。",
                },
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["selected_citation_ids"] == ["S1"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]
    assert result["evidence_items"][0]["excerpt"] == source_excerpt


@pytest.mark.asyncio
async def test_compress_context_accepts_non_verbatim_single_citation_selection_without_fallback() -> None:
    source_excerpt = (
        "AI Agent 的六大核心组件包括：\n"
        "### 感知 (Perception)\n"
        "1. 负责从外部世界获取信息。\n"
        "### 记忆 (Memory)\n"
        "1. 负责存储信息。\n"
        "### 规划 (Planning)\n"
        "1. 负责制定计划。\n"
        "### 推理引擎 (Reasoning Engine)\n"
        "1. 负责分析与决策。\n"
        "### 工具使用 (Tool Use)\n"
        "1. 负责调用外部工具。\n"
        "### 行动 (Action)\n"
        "1. 负责执行具体操作。"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt="AI Agent 的六大核心组件包括感知、记忆、规划、推理引擎、工具使用和行动。",
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "AI Agent 的六大核心组件是什么？",
            "evidence_items": [
                {"citation_id": "S1", "excerpt": source_excerpt},
                {"citation_id": "S2", "excerpt": "AI Agent 的核心优势在于完整的任务处理流程。"},
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["selected_citation_ids"] == ["S1"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]
    assert result["evidence_items"][0]["excerpt"] == source_excerpt


@pytest.mark.asyncio
async def test_compress_context_expands_partial_challenge_excerpt_to_full_source_when_question_requires_multiple_challenges() -> None:
    source_excerpt = (
        "- **面临的挑战：向量表达的对齐与冷启动**\n"
        "    - **对齐**：如何训练模型，使其产出的向量能够真正代表用户的意图和物品的特性。\n"
        "    - **冷启动**：对于没有历史点击数据的新商品，模型难以准确生成其向量。"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt="对于没有历史点击数据的新商品，模型难以准确生成其向量。",
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "Embedding 模型面临哪些挑战？",
            "evidence_items": [
                {"citation_id": "S1", "excerpt": source_excerpt},
                {"citation_id": "S2", "excerpt": "Embedding 模型负责召回。"},
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["selected_citation_ids"] == ["S1"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]
    assert result["evidence_items"][0]["excerpt"] == source_excerpt
    assert "对齐与冷启动" in result["final_context"]


@pytest.mark.asyncio
async def test_compress_context_expands_partial_architecture_excerpt_to_preserve_original_term() -> None:
    source_excerpt = (
        "- **技术架构：交叉编码器 (Cross-Encoder)**\n"
        "    - 将“用户查询”和“单个候选项”**作为一个整体**输入到模型中，进行深度的语义交互和匹配分析。\n"
        "    - 这种方式能更充分地理解查询与候选项之间的细微关联。"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt="将“用户查询”和“单个候选项”**作为一个整体**输入到模型中，进行深度的语义交互和匹配分析。",
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "Re-rank 模型采用什么技术架构？",
            "evidence_items": [
                {"citation_id": "S1", "excerpt": source_excerpt},
                {"citation_id": "S2", "excerpt": "Re-rank 模型负责排序。"},
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["selected_citation_ids"] == ["S1"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]
    assert result["evidence_items"][0]["excerpt"] == source_excerpt
    assert "Cross-Encoder" in result["final_context"]


def test_is_verbatim_subset_normalizes_unicode_hyphen_and_ellipsis() -> None:
    assert (
        _is_verbatim_subset(
            "Re-rank模型...在排序效果与性能之间取得平衡。",
            "Re‑rank模型…在排序效果与性能之间取得平衡。",
        )
        is True
    )


def test_is_verbatim_subset_accepts_trailing_ellipsis_for_source_prefix() -> None:
    assert (
        _is_verbatim_subset(
            "1. **海选阶段 (召回 Recall)**：由 **Embedding模型** 负责。\n"
            "2. **决赛阶段 (排序 Ranking)**：由 **Re-rank模型** 负责，将最…",
            "1. **海选阶段 (召回 Recall)**：由 **Embedding模型** 负责。\n"
            "2. **决赛阶段 (排序 Ranking)**：由 **Re-rank模型** 负责，将最",
        )
        is True
    )


@pytest.mark.asyncio
async def test_compress_context_accepts_markdown_normalized_verbatim_subset() -> None:
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt="缺点：计算成本非常高，速度慢。",
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "Re-rank 模型的缺点是什么？",
            "evidence_items": [
                {
                    "citation_id": "S1",
                    "excerpt": "- **缺点**：计算成本非常高，速度慢。",
                }
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["final_context"] == "[S1] 缺点：计算成本非常高，速度慢。"


@pytest.mark.asyncio
async def test_compress_context_recovers_supported_source_excerpt_when_model_flattens_lines() -> None:
    source_excerpt = (
        "和“单个候选项”**作为一个整体**输入到模型中，进行深度的语义交互和匹配分析。\n"
        "    - 这种方式能更充分地理解查询与候选项之间的细微关联。\n"
        "    - **缺点**：计算成本非常高，速度慢。\n"
        "    - **优点**：因为只处理上一阶段筛选出的小范围候选集，所以总体的响应速度仍然可以接受。\n"
        "\n"
        "- **面临的挑战：算力与性能的平衡**\n"
        "    - 如何在保证排序效果（复杂建模）与维持系统实时响应之间找到最佳平衡点。\n"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S1",
                excerpt=(
                    "技术架构：交叉编码器 (Cross-Encoder) - 将“用户查询”和“单个候选项”**作为一个整体**输入到模型中，"
                    "进行深度的语义交互和匹配分析。 - **缺点**：计算成本非常高，速度慢。 "
                    "- **面临的挑战：算力与性能的平衡** - 如何在保证排序效果（复杂建模）与维持系统实时响应之间找到最佳平衡点。"
                ),
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "Re-rank 模型的技术架构和挑战是什么？",
            "evidence_items": [
                {
                    "citation_id": "S1",
                    "excerpt": source_excerpt,
                }
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["evidence_items"][0]["excerpt"] == source_excerpt.strip()
    assert result["final_context"] == f"[S1] {source_excerpt.strip()}"


@pytest.mark.asyncio
async def test_compress_context_remaps_unique_citation_when_excerpt_matches_other_source() -> None:
    rerank_source_excerpt = (
        "和“单个候选项”**作为一个整体**输入到模型中，进行深度的语义交互和匹配分析。\n"
        "    - 这种方式能更充分地理解查询与候选项之间的细微关联。\n"
        "    - **缺点**：计算成本非常高，速度慢。\n"
        "\n"
        "- **面临的挑战：算力与性能的平衡**\n"
        "    - 如何在保证排序效果（复杂建模）与维持系统实时响应之间找到最佳平衡点。\n"
    )
    embedding_source_excerpt = (
        "- **技术架构：双塔结构 (Dual-Encoder)**\n"
        "    - 一个“塔”专门编码用户查询 (Query)。\n"
        "    - 另一个“塔”专门编码所有商品或内容 (Item)。\n"
    )
    selected_excerpt = (
        "- **面临的挑战：算力与性能的平衡**\n"
        "    - 如何在保证排序效果（复杂建模）与维持系统实时响应之间找到最佳平衡点。"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S5",
                excerpt=selected_excerpt,
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "Re-rank 模型面临什么挑战？",
            "evidence_items": [
                {
                    "citation_id": "S4",
                    "excerpt": rerank_source_excerpt,
                },
                {
                    "citation_id": "S5",
                    "excerpt": embedding_source_excerpt,
                },
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["candidate_citation_ids"] == ["S5"]
    assert result["compression_stats"]["selected_citation_ids"] == ["S4"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S4"]
    assert result["evidence_items"][0]["excerpt"] == selected_excerpt
    assert result["final_context"] == f"[S4] {selected_excerpt}"


@pytest.mark.asyncio
async def test_compress_context_recovers_cited_source_excerpt_when_model_returns_non_verbatim_excerpt() -> None:
    cited_source_excerpt = (
        "1. **海选阶段 (召回 Recall)**：由 **Embedding模型** 负责，像一个高效的“猎人”，"
        "快速从海量信息中捕获所有可能相关的候选项。\n"
        "2. **决赛阶段 (排序 Ranking)**：由 **Re-rank模型** 负责，像一个严格的“裁判”，"
        "对海选出的候选项进行精细化打分和排序，将最匹配的结果排在最前面。"
    )
    neighboring_source_excerpt = (
        "不同复杂度的Re-rank模型协同工作。\n"
        "模型蒸馏 (Knowledge Distillation)：将一个复杂的大模型（教师模型）的知识迁移到一个更小、更快的模型（学生模型）上。"
    )
    payload = ContextCompressDecision(
        decision="subset",
        items=[
            ContextCompressItem(
                citation_id="S5",
                excerpt=(
                    "Embedding 模型负责召回，像猎人一样从海量信息中抓取候选项；"
                    "Re-rank 模型负责排序，像裁判一样把最匹配的结果排到前面。"
                ),
            )
        ],
    )
    fake_model = _FakeChatModel(payload)

    result = await _compress_context(
        state={
            "user_input": "Embedding 模型和 Re-rank 模型分别负责什么？",
            "evidence_items": [
                {
                    "citation_id": "S5",
                    "excerpt": cited_source_excerpt,
                },
                {
                    "citation_id": "S6",
                    "excerpt": neighboring_source_excerpt,
                },
            ],
        },
        runtime=None,
        settings=None,
        chat_model=fake_model,
    )

    assert result["compression_stats"]["fallback_used"] is False
    assert result["compression_stats"]["fallback_reason"] is None
    assert result["compression_stats"]["candidate_citation_ids"] == ["S5"]
    assert result["compression_stats"]["selected_citation_ids"] == ["S5"]
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S5"]
    assert result["evidence_items"][0]["excerpt"] == cited_source_excerpt
    assert result["final_context"] == f"[S5] {cited_source_excerpt}"


@pytest.mark.asyncio
async def test_retrieval_plan_stage_summary_separates_upstream_retry_signal_from_planner_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_plan_retrieval_budget(
        self,
        *,
        question: str,
        normalized_query: str,
        complexity_level: str,
        query_items: list[dict[str, object]],
        retry_count: int,
        failure_reason: str,
        max_top_k: int,
        fallback_budget: dict[str, int],
    ) -> RetrievalPlanResult:
        assert question == "Embedding 模型和 Re-rank 模型分别负责什么？"
        assert normalized_query == question
        assert complexity_level == "simple"
        assert retry_count == 0
        assert failure_reason == "incomplete"
        assert max_top_k == 10
        assert query_items == [{"kind": "main", "query": question}]
        assert fallback_budget["per_query_top_k"] >= 1
        return RetrievalPlanResult(
            budget={
                "per_query_top_k": 6,
                "global_candidates_limit": 24,
                "rerank_input_limit": 12,
            },
            success=True,
            reason=None,
            latency_ms=15,
            meta={
                "decision_source": "llm",
                "fallback_reason": None,
                "fallback_used": False,
                "reasoning": "上游有不完整信号，预算略微提升。",
            },
        )

    monkeypatch.setattr(
        QueryRewriteService,
        "plan_retrieval_budget",
        _fake_plan_retrieval_budget,
    )

    question = "Embedding 模型和 Re-rank 模型分别负责什么？"
    result = await _retrieval_plan_node(
        state={
            "normalized_query": question,
            "complexity_level": "simple",
            "query_items": [{"kind": "main", "query": question}],
            "reflection": {"reason": "incomplete"},
        },
        runtime=None,
        settings=SimpleNamespace(retrieval_max_top_k=10),
    )

    summary = result["stage_summaries"]["retrieval_plan"]
    assert summary["failure_reason"] is None
    assert summary["fallback_reason"] is None
    assert summary["upstream_retry_signal"] == "incomplete"


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
async def test_classify_complexity_guardrail_downgrades_stable_overview_from_multi_query_to_direct() -> None:
    service = QueryRewriteService()
    query = "AI Agent 的六大核心组件是什么？"

    async def _misclassified_structured_call(
        *,
        schema: type[ComplexityDecision],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        assert schema is ComplexityDecision
        assert query in user_prompt
        assert max_tokens == 256
        return StructuredCallResult(
            payload=ComplexityDecision(
                reasoning="含中英混写，改写更稳。",
                strategy="multi_query",
                confidence=0.88,
                risk_flags=["mixed_language"],
                decision_version="kb_chat_complexity_classify_v5",
            ),
            success=True,
            reason="ok",
            latency_ms=11,
        )

    service._invoke_model_structured = _misclassified_structured_call  # type: ignore[method-assign]

    result = await service.classify_complexity(
        query,
        recall_risk="medium",
        has_multi_target=False,
        is_comparison=False,
    )

    assert result.success is True
    assert result.strategy == "direct"
    assert result.failure_reason is None
    assert result.decision_version == "kb_chat_complexity_classify_v5"


@pytest.mark.asyncio
async def test_classify_complexity_guardrail_upgrades_multi_target_from_multi_query_to_decomposition() -> None:
    service = QueryRewriteService()
    query = "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？"

    async def _misclassified_structured_call(
        *,
        schema: type[ComplexityDecision],
        user_prompt: str,
        max_tokens: int,
    ) -> StructuredCallResult:
        assert schema is ComplexityDecision
        assert query in user_prompt
        assert max_tokens == 256
        return StructuredCallResult(
            payload=ComplexityDecision(
                reasoning="术语存在中英混写，适合多路改写。",
                strategy="multi_query",
                confidence=0.91,
                risk_flags=["mixed_language", "term_alias"],
                decision_version="kb_chat_complexity_classify_v5",
            ),
            success=True,
            reason="ok",
            latency_ms=13,
        )

    service._invoke_model_structured = _misclassified_structured_call  # type: ignore[method-assign]

    result = await service.classify_complexity(
        query,
        recall_risk="medium",
        has_multi_target=False,
        is_comparison=False,
    )

    assert result.success is True
    assert result.strategy == "decomposition"
    assert result.failure_reason is None
    assert "mixed_language" in result.risk_flags


@pytest.mark.asyncio
async def test_normalize_rewrite_guardrail_preserves_stable_overview_query_when_model_cross_language_compresses() -> None:
    service = QueryRewriteService()
    query = "AI Agent 的六大核心组件是什么？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[NormalizeDecision],
        max_tokens: int,
        question: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/normalize_query"
        assert schema is NormalizeDecision
        assert max_tokens == 320
        assert question == query
        return StructuredCallResult(
            payload=NormalizeDecision(
                canonical_query="AI Agent six core components",
                aliases=["AI Agent core modules"],
                entities=["AI Agent"],
                time_constraints=[],
                metric_constraints=[],
                scope_constraints=[],
                recall_risk="low",
                drift_risk=False,
                constraint_preserved=True,
                has_multi_target=False,
                is_comparison=False,
                reasoning="保留核心实体，但压缩为英文短语。",
            ),
            success=True,
            reason="ok",
            latency_ms=7,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.normalize_rewrite(query)

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta == {
        "source": "guardrail_preserve_original",
        "fallback_reason": "stable_overview_cross_language_drift",
        "guardrail_reason": "stable_overview_cross_language_drift",
        "aliases": ["AI Agent core modules"],
        "entities": ["AI Agent"],
        "time_constraints": [],
        "metric_constraints": [],
        "scope_constraints": [],
        "recall_risk": "low",
        "drift_risk": False,
        "constraint_preserved": True,
        "has_multi_target": False,
        "is_comparison": False,
        "reasoning": "保留核心实体，但压缩为英文短语。",
    }


@pytest.mark.asyncio
async def test_normalize_rewrite_guardrail_preserves_stable_overview_query_when_model_drops_question_form() -> None:
    service = QueryRewriteService()
    query = "AI Agent 的六大核心组件是什么？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[NormalizeDecision],
        max_tokens: int,
        question: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/normalize_query"
        assert schema is NormalizeDecision
        assert max_tokens == 320
        assert question == query
        return StructuredCallResult(
            payload=NormalizeDecision(
                canonical_query="AI Agent 六大核心组件",
                aliases=["AI Agent 核心模块"],
                entities=["AI Agent"],
                time_constraints=[],
                metric_constraints=[],
                scope_constraints=[],
                recall_risk="low",
                drift_risk=False,
                constraint_preserved=True,
                has_multi_target=False,
                is_comparison=False,
                reasoning="保留实体并压缩成名词短语。",
            ),
            success=True,
            reason="ok",
            latency_ms=8,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.normalize_rewrite(query)

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta is not None
    assert result.meta["fallback_reason"] == "stable_overview_ask_lost"
    assert result.meta["guardrail_reason"] == "stable_overview_ask_lost"


@pytest.mark.asyncio
async def test_normalize_rewrite_guardrail_preserves_taxonomy_query_when_model_collapses_to_cross_language_overview() -> None:
    service = QueryRewriteService()
    query = "Chain-of-Thought（CoT，思维链）的主要变体有哪些？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[NormalizeDecision],
        max_tokens: int,
        question: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/normalize_query"
        assert schema is NormalizeDecision
        assert max_tokens == 320
        assert question == query
        return StructuredCallResult(
            payload=NormalizeDecision(
                canonical_query="Chain-of-Thought variants",
                aliases=["CoT variants"],
                entities=["Chain-of-Thought", "CoT", "思维链"],
                time_constraints=[],
                metric_constraints=[],
                scope_constraints=[],
                recall_risk="medium",
                drift_risk=False,
                constraint_preserved=True,
                has_multi_target=False,
                is_comparison=False,
                reasoning="压缩为英文术语短语，便于检索。",
            ),
            success=True,
            reason="ok",
            latency_ms=8,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.normalize_rewrite(query)

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta is not None
    assert result.meta["fallback_reason"] == "taxonomy_cross_language_drift"
    assert result.meta["guardrail_reason"] == "taxonomy_cross_language_drift"
    assert result.meta["aliases"] == ["CoT variants"]
    assert result.meta["entities"] == ["Chain-of-Thought", "CoT", "思维链"]


@pytest.mark.asyncio
async def test_normalize_rewrite_guardrail_preserves_multi_target_query_when_model_drops_one_entity() -> None:
    service = QueryRewriteService()
    query = "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[NormalizeDecision],
        max_tokens: int,
        question: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/normalize_query"
        assert schema is NormalizeDecision
        assert max_tokens == 320
        assert question == query
        return StructuredCallResult(
            payload=NormalizeDecision(
                canonical_query="Embedding 模型 负责 什么 技术 架构 如何 各自 面临 哪些 挑战",
                aliases=["Embedding Dual-Encoder challenge"],
                entities=["Embedding 模型", "Re-rank 模型"],
                time_constraints=[],
                metric_constraints=[],
                scope_constraints=[],
                recall_risk="medium",
                drift_risk=False,
                constraint_preserved=True,
                has_multi_target=True,
                is_comparison=False,
                reasoning="保留了主要技术方向，但将问题聚焦到召回侧。",
            ),
            success=True,
            reason="ok",
            latency_ms=9,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.normalize_rewrite(query)

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta is not None
    assert result.meta["fallback_reason"] == "multi_target_entity_lost"
    assert result.meta["guardrail_reason"] == "multi_target_entity_lost"
    assert result.meta["has_multi_target"] is True
    assert result.meta["entities"] == ["Embedding 模型", "Re-rank 模型"]


@pytest.mark.asyncio
async def test_transform_query_guardrail_preserves_stable_overview_query_when_model_cross_language_compresses() -> None:
    service = QueryRewriteService()
    query = "AI Agent 的六大核心组件是什么？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[TransformQueryDecision],
        max_tokens: int,
        question: str,
        reason: str,
        hint: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/transform_query"
        assert schema is TransformQueryDecision
        assert max_tokens == 96
        assert question == query
        assert reason == "incomplete"
        assert hint == ""
        return StructuredCallResult(
            payload=TransformQueryDecision(query="AI Agent six core components"),
            success=True,
            reason="ok",
            latency_ms=9,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.transform_query(
        query,
        reason="incomplete",
        hint=None,
        enabled=True,
    )

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta == {
        "source": "guardrail_preserve_original",
        "fallback_reason": "stable_overview_cross_language_drift",
        "guardrail_reason": "stable_overview_cross_language_drift",
    }


@pytest.mark.asyncio
async def test_transform_query_guardrail_preserves_stable_overview_query_when_model_drops_question_form() -> None:
    service = QueryRewriteService()
    query = "AI Agent 的六大核心组件是什么？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[TransformQueryDecision],
        max_tokens: int,
        question: str,
        reason: str,
        hint: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/transform_query"
        assert schema is TransformQueryDecision
        assert max_tokens == 96
        assert question == query
        assert reason == "incomplete"
        assert hint == ""
        return StructuredCallResult(
            payload=TransformQueryDecision(query="AI Agent 六大核心组件"),
            success=True,
            reason="ok",
            latency_ms=9,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.transform_query(
        query,
        reason="incomplete",
        hint=None,
        enabled=True,
    )

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta == {
        "source": "guardrail_preserve_original",
        "fallback_reason": "stable_overview_ask_lost",
        "guardrail_reason": "stable_overview_ask_lost",
    }


@pytest.mark.asyncio
async def test_transform_query_guardrail_preserves_taxonomy_query_when_retry_broadens_to_methods_examples() -> None:
    service = QueryRewriteService()
    query = "Chain-of-Thought（CoT，思维链）的主要变体有哪些？"

    async def _fake_structured_call(
        prompt_key: str,
        *,
        schema: type[TransformQueryDecision],
        max_tokens: int,
        question: str,
        reason: str,
        hint: str,
    ) -> StructuredCallResult:
        assert prompt_key == "kb_chat/transform_query"
        assert schema is TransformQueryDecision
        assert max_tokens == 96
        assert question == query
        assert reason == "incomplete"
        assert hint == ""
        return StructuredCallResult(
            payload=TransformQueryDecision(
                query="Chain-of-Thought variants methods techniques examples"
            ),
            success=True,
            reason="ok",
            latency_ms=9,
        )

    service._call_prompt_structured = _fake_structured_call  # type: ignore[method-assign]

    result = await service.transform_query(
        query,
        reason="incomplete",
        hint=None,
        enabled=True,
    )

    assert result.query == query
    assert result.rewritten is False
    assert result.reason == "guardrail_preserve_original"
    assert result.meta == {
        "source": "guardrail_preserve_original",
        "fallback_reason": "taxonomy_cross_language_drift",
        "guardrail_reason": "taxonomy_cross_language_drift",
    }


@pytest.mark.asyncio
async def test_transform_query_for_retry_preserves_original_stable_overview_query_during_replanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_transform_query(
        self,
        query: str,
        *,
        reason: str,
        hint: str | None = None,
        enabled: bool = True,
    ) -> RewriteResult:
        assert query == "AI Agent 的六大核心组件是什么？"
        assert reason == "incomplete"
        assert hint is None
        assert enabled is True
        return RewriteResult(
            query="AI Agent 六大核心组件",
            rewritten=True,
            reason="ok",
            latency_ms=11,
        )

    async def _fake_normalize_rewrite(
        self,
        query: str,
    ) -> RewriteResult:
        assert query == "AI Agent 六大核心组件"
        return RewriteResult(
            query="AI Agent 六大核心组件",
            rewritten=True,
            reason="ok",
            latency_ms=7,
            meta={"source": "llm_structured"},
        )

    captured_state: dict[str, object] = {}

    async def _fake_run_query_plan_scheme_b(
        state: dict[str, object],
        *,
        runtime: object,
        settings: object,
    ) -> dict[str, object]:
        captured_state.update(state)
        return {
            "query_strategy": "direct",
            "query_items": [{"kind": "main", "query": "AI Agent 六大核心组件"}],
            "query_plan_result": {},
            "query_plan_diagnostics": {"fallback_reason": "none"},
            "stage_summaries": {},
            "sub_queries": [],
            "multi_queries": [],
            "hyde_docs": [],
            "decomposition_plan": {},
        }

    monkeypatch.setattr(QueryRewriteService, "transform_query", _fake_transform_query)
    monkeypatch.setattr(QueryRewriteService, "normalize_rewrite", _fake_normalize_rewrite)
    monkeypatch.setattr(
        reflection_module,
        "run_query_plan_scheme_b",
        _fake_run_query_plan_scheme_b,
    )

    result = await reflection_module.transform_query_for_retry(
        {
            "user_input": "AI Agent 的六大核心组件是什么？",
            "resolved_query": "AI Agent 的六大核心组件是什么？",
            "coref_query": "AI Agent 的六大核心组件是什么？",
            "rewrite_input_query": "AI Agent 的六大核心组件是什么？",
            "normalized_query": "AI Agent 的六大核心组件是什么？",
            "normalized_meta": {"source": "llm_structured"},
            "stage_summaries": {},
            "loop_counts": {"total_rounds": 0, "retrieval_retries": 0, "generation_retries": 0},
            "reflection": {"reason": "incomplete"},
        },
        settings=SimpleNamespace(kb_chat_max_retrieval_retries=2),
        runtime=None,
    )

    assert captured_state["resolved_query"] == "AI Agent 的六大核心组件是什么？"
    assert captured_state["coref_query"] == "AI Agent 的六大核心组件是什么？"
    assert captured_state["rewrite_input_query"] == "AI Agent 的六大核心组件是什么？"
    assert captured_state["normalized_query"] == "AI Agent 六大核心组件"
    assert result["normalized_query"] == "AI Agent 六大核心组件"
    assert result["query_items"] == [{"kind": "main", "query": "AI Agent 六大核心组件"}]


@pytest.mark.asyncio
async def test_query_normalize_stage_summary_treats_guardrail_as_non_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_normalize_rewrite(
        self,
        query: str,
    ) -> RewriteResult:
        assert query == "AI Agent 的六大核心组件是什么？"
        return RewriteResult(
            query=query,
            rewritten=False,
            reason="guardrail_preserve_original",
            latency_ms=9,
            meta={
                "source": "guardrail_preserve_original",
                "fallback_reason": "stable_overview_ask_lost",
                "guardrail_reason": "stable_overview_ask_lost",
                "aliases": ["AI Agent 核心模块"],
                "entities": ["AI Agent"],
                "time_constraints": [],
                "metric_constraints": [],
                "scope_constraints": [],
                "recall_risk": "low",
                "drift_risk": False,
                "constraint_preserved": True,
                "reasoning": "结构化输出成功，但触发保守护栏。",
            },
        )

    monkeypatch.setattr(QueryRewriteService, "normalize_rewrite", _fake_normalize_rewrite)

    result = await preprocess_module.normalize_rewrite(
        {"resolved_query": "AI Agent 的六大核心组件是什么？", "stage_summaries": {}},
        settings=SimpleNamespace(app_env="test", kb_chat_json_safe_policy="fail_fast"),
        runtime=None,
    )

    summary = result["stage_summaries"]["query_normalize"]
    assert summary["normalization_source"] == "guardrail_preserve_original"
    assert summary["fallback_reason"] is None
    assert summary["guardrail_reason"] == "stable_overview_ask_lost"


@pytest.mark.asyncio
async def test_resolve_reference_stage_summary_clears_llm_success_fallback_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_resolve_reference(
        self,
        query: str,
        *,
        enabled: bool = True,
        recent_turns: list[dict[str, str]] | None = None,
        summary_text: str | None = None,
        memory_snippet: str | None = None,
    ) -> RewriteResult:
        assert enabled is True
        assert recent_turns == []
        assert summary_text == ""
        assert memory_snippet == ""
        return RewriteResult(
            query=query,
            rewritten=False,
            reason="llm_structured",
            latency_ms=8,
            meta={
                "triggered": False,
                "confidence": 0.99,
                "selected_mention": "",
                "resolution_source": "llm_structured",
                "reasoning": "问题已自足，无需消解。",
                "needs_clarification": False,
            },
        )

    monkeypatch.setattr(QueryRewriteService, "resolve_reference", _fake_resolve_reference)

    result = await preprocess_module.coref_rewrite(
        {
            "rewrite_input_query": "AI Agent 的六大核心组件是什么？",
            "context_frame": {"selected_turns": [], "summary_text": "", "memory_snippet": ""},
            "stage_summaries": {},
        },
        settings=SimpleNamespace(app_env="test", kb_chat_json_safe_policy="fail_fast"),
    )

    summary = result["stage_summaries"]["resolve_reference"]
    assert summary["resolution_source"] == "llm_structured"
    assert summary["reason"] == "llm_structured"
    assert summary["fallback_reason"] is None


def test_query_plan_finalize_stage_summary_clears_none_fallback_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preprocess_module,
        "resolve_prepare_budget",
        lambda *, state, runtime, settings: {"per_query_top_k": 4, "global_candidates_limit": 16},
    )
    monkeypatch.setattr(
        preprocess_module,
        "build_prepared_query_bundle",
        lambda **kwargs: {
            "query_items": [{"kind": "main", "query": kwargs["normalized_query"]}],
            "message_plan": {"candidates": [{"kind": "main"}], "dropped": [], "budget": {"per_query_top_k": 4}},
            "query_bundle": {"kind_breakdown": {"main": 1}, "dedup_stats": {}},
            "prepare_diagnostics": {"fallback_reason": "none", "quality_signals": []},
        },
    )

    update = preprocess_module._build_query_plan_finalize_update(
        state={
            "user_input": "AI Agent 的六大核心组件是什么？",
            "resolved_query": "AI Agent 的六大核心组件是什么？",
            "normalized_query": "AI Agent 的六大核心组件是什么？",
            "query_strategy": "direct",
            "stage_summaries": {},
        },
        runtime=None,
        settings=SimpleNamespace(app_env="test", kb_chat_json_safe_policy="fail_fast"),
        latency_ms=5,
    )

    assert update["stage_summaries"]["query_plan_finalize"]["fallback_reason"] is None


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
