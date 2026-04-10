from __future__ import annotations

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from app.integrations.llamacpp_chat_model import LlamaCppChatOpenAI
from app.services.streaming import DeltaKind, extract_stream_delta


def test_extract_stream_delta_supports_reasoning_content_string() -> None:
    token = AIMessageChunk(
        content="",
        additional_kwargs={"reasoning_content": "step-1"},
    )

    deltas = extract_stream_delta(token)

    assert len(deltas) == 1
    assert deltas[0].kind == DeltaKind.THINKING
    assert deltas[0].content == "step-1"


def test_llamacpp_stream_chunk_preserves_reasoning_content() -> None:
    model = LlamaCppChatOpenAI(
        model="gemma-4-e2b-it-Q8_0.gguf",
        api_key="not-needed",
        base_url="http://127.0.0.1:8080/v1",
        use_responses_api=False,
        max_retries=0,
    )

    generation_chunk = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,
                    "delta": {"reasoning_content": "raw-thinking"},
                }
            ],
            "model": "gemma-4-e2b-it-Q8_0.gguf",
        },
        AIMessageChunk,
        None,
    )

    assert isinstance(generation_chunk, ChatGenerationChunk)
    message = generation_chunk.message
    assert message.additional_kwargs["reasoning_content"] == "raw-thinking"
    assert message.additional_kwargs["reasoning"] == {"reasoning": "raw-thinking"}

    deltas = extract_stream_delta(message)
    assert len(deltas) == 1
    assert deltas[0].kind == DeltaKind.THINKING
    assert deltas[0].content == "raw-thinking"


def test_llamacpp_non_stream_result_preserves_reasoning_content() -> None:
    model = LlamaCppChatOpenAI(
        model="gemma-4-e2b-it-Q8_0.gguf",
        api_key="not-needed",
        base_url="http://127.0.0.1:8080/v1",
        use_responses_api=False,
        max_retries=0,
    )

    result = model._create_chat_result(
        {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "final-answer",
                        "reasoning_content": "final-thinking",
                    },
                }
            ],
            "model": "gemma-4-e2b-it-Q8_0.gguf",
        }
    )

    message = result.generations[0].message
    assert message.content == "final-answer"
    assert message.additional_kwargs["reasoning_content"] == "final-thinking"
    assert message.additional_kwargs["reasoning"] == {"reasoning": "final-thinking"}
