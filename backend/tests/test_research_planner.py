import json
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage

from app.integrations.model_runtime_config import (
    ModelRuntimeConfigManager,
    RuntimeModelSnapshot,
    RuntimeProviderConfig,
)
from app.models.model_config import ModelProvider
from app.schemas.research import ResearchComplexity
from app.services import research_planner as planner_module


class _FakePromptLoader:
    def render_with_few_shot(self, key: str, **kwargs: object) -> str:
        question = str(kwargs.get("question") or "").strip()
        if key == "research/scoper_user":
            return f"LEGACY_FULL_SCOPER_USER_PROMPT:{question}"
        if question:
            return f"{key}:{question}"
        return key


class _FakeStructuredModel:
    def __init__(self, response: object, *, method: str, invocations: list[tuple[str, object]]) -> None:
        self._response = response
        self._method = method
        self._invocations = invocations

    async def ainvoke(self, messages: object) -> object:
        self._invocations.append((self._method, messages))
        return self._response


class _FakeChatModel:
    def __init__(self, responses: dict[str, object | list[object]]) -> None:
        self._responses = {
            method: value if isinstance(value, list) else [value]
            for method, value in responses.items()
        }
        self.methods: list[str] = []
        self.invocations: list[tuple[str, object]] = []

    def with_structured_output(
        self,
        schema: object,
        *,
        method: str,
        include_raw: bool,
    ) -> _FakeStructuredModel:
        del schema, include_raw
        self.methods.append(method)
        queue = self._responses[method]
        response = queue.pop(0)
        return _FakeStructuredModel(
            response,
            method=method,
            invocations=self.invocations,
        )


def _build_snapshot(provider: ModelProvider) -> RuntimeModelSnapshot:
    return RuntimeModelSnapshot(
        providers={
            provider: RuntimeProviderConfig(
                provider=provider,
                enabled=True,
                base_url="http://127.0.0.1:11434" if provider == ModelProvider.OLLAMA else None,
                api_key=None,
                models=["fake-model"],
                thinking_enabled=True,
                thinking_level="high",
            )
        },
        active_provider=provider,
        active_model="fake-model",
        updated_at=datetime.now(timezone.utc),
    )


def _empty_structured_result() -> dict[str, object]:
    return {
        "raw": AIMessage(content=""),
        "parsed": None,
        "parsing_error": None,
    }


def _json_mode_result() -> dict[str, object]:
    payload = {
        "decision": "proceed",
        "summary": "聚焦 2025 年中国 AI Agent 开源框架现状，优先核查官方仓库与技术资料。",
        "research_brief": "研究 2025 年中国 AI Agent 开源框架的发展现状，比较主流项目定位、能力边界与生态成熟度。",
        "complexity": "simple",
        "target_sources": ["web"],
        "subtasks": [
            {
                "title": "框架清单",
                "description": "收集主流中国 AI Agent 开源框架及其官方资料。",
                "target_sources": ["web"],
            }
        ],
        "budget_guidance": "优先官方仓库、官方文档与项目公告。",
    }
    return {
        "raw": AIMessage(content=json.dumps(payload, ensure_ascii=False)),
        "parsed": None,
        "parsing_error": None,
    }


def _json_mode_decision_result(decision: str) -> dict[str, object]:
    return {
        "raw": AIMessage(content=json.dumps({"decision": decision}, ensure_ascii=False)),
        "parsed": None,
        "parsing_error": None,
    }


def _json_mode_clarify_result() -> dict[str, object]:
    payload = {
        "summary": "当前问题仍缺少会改变研究路径的关键边界，需要先澄清。",
        "questions": [
            {
                "id": "q1",
                "question": "你更关注框架能力对比，还是生态成熟度对比？",
                "why_it_matters": "这会改变后续证据收集和比较维度。",
            }
        ],
    }
    return {
        "raw": AIMessage(content=json.dumps(payload, ensure_ascii=False)),
        "parsed": None,
        "parsing_error": None,
    }


@pytest.mark.asyncio
async def test_scope_uses_json_mode_for_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = _FakeChatModel(
        {
            "json_mode": [
                _json_mode_decision_result("proceed"),
                _json_mode_result(),
            ],
        }
    )
    monkeypatch.setattr(planner_module, "get_prompt_loader", lambda: _FakePromptLoader())
    monkeypatch.setattr(planner_module, "create_chat_model", lambda **kwargs: fake_model)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda settings=None: _build_snapshot(ModelProvider.OLLAMA),
    )

    scoper = planner_module.LLMResearchScoper()

    result = await scoper.scope(question="研究 2025 年中国 AI Agent 开源框架的发展现状")

    assert fake_model.methods == ["json_mode", "json_mode"]
    decision_messages = fake_model.invocations[0][1]
    proceed_messages = fake_model.invocations[1][1]
    assert len(decision_messages) == 2
    assert len(proceed_messages) == 2
    assert "\"decision\"" in decision_messages[1].content
    assert "只能返回 decision" in decision_messages[1].content
    assert "LEGACY_FULL_SCOPER_USER_PROMPT" not in decision_messages[1].content
    assert "LEGACY_FULL_SCOPER_USER_PROMPT" not in proceed_messages[1].content
    assert "research_brief 必须是单个字符串字段" in proceed_messages[1].content
    assert "不能把 complexity、target_sources、subtasks" in proceed_messages[1].content
    assert result.complexity == ResearchComplexity.SIMPLE
    assert result.target_sources[0].value == "web"
    assert result.subtasks[0].title == "框架清单"


@pytest.mark.asyncio
async def test_scope_uses_two_stage_json_mode_for_ollama_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model = _FakeChatModel(
        {
            "json_mode": [
                _json_mode_decision_result("clarify"),
                _json_mode_clarify_result(),
            ],
        }
    )
    monkeypatch.setattr(planner_module, "get_prompt_loader", lambda: _FakePromptLoader())
    monkeypatch.setattr(planner_module, "create_chat_model", lambda **kwargs: fake_model)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda settings=None: _build_snapshot(ModelProvider.OLLAMA),
    )

    scoper = planner_module.LLMResearchScoper()

    result = await scoper.scope(question="研究 2025 年中国 AI Agent 开源框架的发展现状")

    assert fake_model.methods == ["json_mode", "json_mode"]
    clarify_messages = fake_model.invocations[1][1]
    assert "questions" in clarify_messages[1].content
    assert "只生成澄清请求" in clarify_messages[1].content
    assert "LEGACY_FULL_SCOPER_USER_PROMPT" not in clarify_messages[1].content
    assert result.questions[0].id == "q1"
    assert "生态成熟度" in result.questions[0].question


@pytest.mark.asyncio
async def test_scope_keeps_function_calling_only_for_non_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model = _FakeChatModel(
        {
            "function_calling": _empty_structured_result(),
            "json_mode": _json_mode_result(),
        }
    )
    monkeypatch.setattr(planner_module, "get_prompt_loader", lambda: _FakePromptLoader())
    monkeypatch.setattr(planner_module, "create_chat_model", lambda **kwargs: fake_model)
    monkeypatch.setattr(
        ModelRuntimeConfigManager,
        "get_snapshot",
        lambda settings=None: _build_snapshot(ModelProvider.OPENAI),
    )

    scoper = planner_module.LLMResearchScoper()

    with pytest.raises(RuntimeError, match="empty_structured_response"):
        await scoper.scope(question="研究 2025 年中国 AI Agent 开源框架的发展现状")

    assert fake_model.methods == ["function_calling"]
    non_ollama_messages = fake_model.invocations[0][1]
    assert "LEGACY_FULL_SCOPER_USER_PROMPT" in non_ollama_messages[1].content
