from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.settings import Settings
from app.integrations.langchain_profiles import build_chat_model_profile


def _build_settings() -> Settings:
    return Settings(
        llm_model="moonshotai/kimi-k2.5",
        llm_api_key="test-key",
        llm_base_url="https://example.com/v1",
        llm_max_input_tokens=204800,
        mcp_enabled=True,
    )


def _build_model(**kwargs: object) -> ChatOpenAI:
    settings = _build_settings()
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url.rstrip("/"),
        profile=build_chat_model_profile(settings),
        **kwargs,
    )


def test_current_profile_only_sets_max_input_tokens() -> None:
    profile = build_chat_model_profile(_build_settings())
    assert profile == {"max_input_tokens": 204800}


def test_mcp_enabled_does_not_enable_reasoning_by_default() -> None:
    model = _build_model()
    payload = model._get_request_payload([HumanMessage(content="ping")])

    assert "reasoning" not in payload
    assert "messages" in payload
    assert "input" not in payload


def test_reasoning_can_be_enabled_in_model_config() -> None:
    reasoning = {"effort": "medium", "summary": "auto"}
    model = _build_model(reasoning=reasoning, output_version="responses/v1")
    payload = model._get_request_payload([HumanMessage(content="ping")])

    assert payload["reasoning"] == reasoning
    assert "input" in payload
    assert "messages" not in payload


def test_reasoning_can_be_enabled_per_invocation() -> None:
    model = _build_model()
    reasoning = {"effort": "low", "summary": "auto"}
    payload = model._get_request_payload(
        [HumanMessage(content="ping")],
        reasoning=reasoning,
    )

    assert payload["reasoning"] == reasoning
    assert "input" in payload
    assert "messages" not in payload
