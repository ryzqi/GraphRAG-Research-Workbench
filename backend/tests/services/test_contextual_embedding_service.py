from __future__ import annotations

import logging

import pytest
from app.core.settings import Settings
from app.services.contextual_embedding_service import (
    ContextualEmbeddingService,
    _LLMCallOutput,
)


def _make_settings() -> Settings:
    return Settings(
        llm_model="test-model",
        llm_api_key="test-key",
        llm_base_url="https://example.test/v1",
    )


@pytest.mark.asyncio
async def test_generate_logs_metadata_when_output_is_empty(caplog: pytest.LogCaptureFixture) -> None:
    service = ContextualEmbeddingService(settings=_make_settings())

    async def _fake_call_llm(_prompt: str) -> _LLMCallOutput:
        return _LLMCallOutput(
            text="",
            finish_reason="length",
            prompt_tokens=12,
            completion_tokens=64,
        )

    service._call_llm = _fake_call_llm  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger="app.services.contextual_embedding_service"):
        result = await service.generate(
            full_text="文档背景",
            chunk="分块正文",
            enabled=True,
            max_tokens=64,
        )

    assert result.success is False
    assert result.reason == "empty_output"

    empty_record = next(
        record for record in caplog.records if record.message == "Context 生成为空"
    )
    assert empty_record.finish_reason == "length"
    assert empty_record.prompt_tokens == 12
    assert empty_record.completion_tokens == 64


@pytest.mark.asyncio
async def test_call_llm_extracts_visible_text_without_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ContextualEmbeddingService(settings=_make_settings())

    bind_called = False

    class _FakeResult:
        content = "<think>internal</think>最终答案"
        response_metadata = {
            "finish_reason": "stop",
            "token_usage": {"prompt_tokens": 5, "completion_tokens": 7},
        }

    class _FakeChatOpenAI:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def bind(self, **_kwargs: object) -> "_FakeChatOpenAI":
            nonlocal bind_called
            bind_called = True
            return self

        def invoke(self, _messages: list[object]) -> _FakeResult:
            return _FakeResult()

    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", _FakeChatOpenAI)

    output = await service._call_llm("prompt")

    assert bind_called is False
    assert output.text == "最终答案"
    assert output.finish_reason == "stop"
    assert output.prompt_tokens == 5
    assert output.completion_tokens == 7
