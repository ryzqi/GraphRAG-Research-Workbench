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
        if question:
            return f"{key}:{question}"
        return key


class _FakeStructuredModel:
    def __init__(self, response: object) -> None:
        self._response = response

    async def ainvoke(self, messages: object) -> object:
        return self._response


class _FakeChatModel:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.methods: list[str] = []

    def with_structured_output(
        self,
        schema: object,
        *,
        method: str,
        include_raw: bool,
    ) -> _FakeStructuredModel:
        del schema, include_raw
        self.methods.append(method)
        return _FakeStructuredModel(self._responses[method])


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


def _json_schema_result() -> dict[str, object]:
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


@pytest.mark.asyncio
async def test_scope_falls_back_to_json_schema_for_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = _FakeChatModel(
        {
            "function_calling": _empty_structured_result(),
            "json_schema": _json_schema_result(),
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

    assert fake_model.methods == ["function_calling", "json_schema"]
    assert result.complexity == ResearchComplexity.SIMPLE
    assert result.target_sources[0].value == "web"
    assert result.subtasks[0].title == "框架清单"


@pytest.mark.asyncio
async def test_scope_keeps_function_calling_only_for_non_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model = _FakeChatModel(
        {
            "function_calling": _empty_structured_result(),
            "json_schema": _json_schema_result(),
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
