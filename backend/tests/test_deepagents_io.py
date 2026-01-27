from types import SimpleNamespace

import pytest

from app.agents.deepagents_io import build_user_messages, extract_last_message_text


def test_build_user_messages() -> None:
    assert build_user_messages("hi") == {
        "messages": [{"role": "user", "content": "hi"}]
    }


def test_extract_last_message_text_from_dict() -> None:
    result = {"messages": [{"role": "assistant", "content": "ok"}]}
    assert extract_last_message_text(result) == "ok"


def test_extract_last_message_text_from_message_object() -> None:
    result = {"messages": [SimpleNamespace(content="pong")]}
    assert extract_last_message_text(result) == "pong"


def test_extract_last_message_text_missing_messages() -> None:
    with pytest.raises(ValueError, match="messages"):
        extract_last_message_text({"messages": []})


def test_extract_last_message_text_non_dict() -> None:
    with pytest.raises(TypeError, match="dict"):
        extract_last_message_text("bad-result")
