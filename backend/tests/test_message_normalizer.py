from __future__ import annotations

from langchain.messages import AIMessage

from app.services.message_normalizer import (
    checkpoint_messages_require_reset,
    extract_response_id,
    extract_text_content,
)


def test_extract_text_content_supports_output_text_blocks() -> None:
    content = [
        {"type": "output_text", "text": "你好"},
        {"type": "text", "text": "，世界"},
    ]
    assert extract_text_content(content, include_output_text=True) == "你好，世界"
    assert extract_text_content(content, include_output_text=False) == "，世界"


def test_checkpoint_messages_require_reset_for_responses_output_message() -> None:
    messages = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "你好"}],
        }
    ]
    assert checkpoint_messages_require_reset(messages) is True


def test_checkpoint_messages_require_reset_requires_assistant_response_id() -> None:
    safe_messages = [
        AIMessage(content="你好", response_metadata={"id": "resp_123"}),
        {"type": "human", "content": "你是谁"},
    ]
    unsafe_messages = [AIMessage(content="你好")]

    assert (
        checkpoint_messages_require_reset(
            safe_messages, require_assistant_response_id=True
        )
        is False
    )
    assert (
        checkpoint_messages_require_reset(
            unsafe_messages, require_assistant_response_id=True
        )
        is True
    )


def test_extract_response_id_from_ai_message() -> None:
    message = AIMessage(content="ok", response_metadata={"id": "resp_abc"})
    assert extract_response_id(message) == "resp_abc"


def test_extract_response_id_from_message_id_field() -> None:
    message = AIMessage(content="ok", id="resp_top_level")
    assert extract_response_id(message) == "resp_top_level"


def test_extract_response_id_rejects_non_response_api_ids() -> None:
    message = AIMessage(content="ok", response_metadata={"id": "chatcmpl_123"})
    assert extract_response_id(message) is None
