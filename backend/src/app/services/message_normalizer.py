from __future__ import annotations

from typing import Any, Sequence

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages import messages_from_dict

_UNSAFE_RESPONSE_ITEM_TYPES = {
    "message",
    "reasoning",
    "output_text",
    "output_image",
    "output_audio",
}

_SAFE_CONTENT_BLOCK_TYPES = {
    "text",
    "input_text",
    "image",
    "input_image",
    "image_url",
    "file",
    "input_file",
    "audio",
    "input_audio",
    "video",
}

_TEXT_BLOCK_TYPES = {
    "text",
    "input_text",
    "output_text",
}

_LANGCHAIN_MESSAGE_TYPES = (AIMessage, HumanMessage, SystemMessage, ToolMessage)


def extract_text_content(content: object, *, include_output_text: bool = True) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "").strip().lower()
        if block_type not in _TEXT_BLOCK_TYPES:
            continue
        if block_type == "output_text" and not include_output_text:
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def extract_response_id(message: object) -> str | None:
    def _normalize_response_id(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized or not normalized.startswith("resp_"):
            return None
        return normalized

    response_metadata: object | None = None
    message_id: object | None = None
    if isinstance(message, _LANGCHAIN_MESSAGE_TYPES):
        response_metadata = getattr(message, "response_metadata", None)
        message_id = getattr(message, "id", None)
    elif isinstance(message, dict):
        payload = _message_payload_dict(message)
        response_metadata = payload.get("response_metadata")
        message_id = payload.get("id")

    if isinstance(response_metadata, dict):
        response_id = _normalize_response_id(response_metadata.get("id"))
        if response_id is not None:
            return response_id

    response_id = _normalize_response_id(message_id)
    if response_id is not None:
        return response_id
    return None


def checkpoint_messages_require_reset(
    messages: object,
    *,
    require_assistant_response_id: bool = False,
) -> bool:
    if not isinstance(messages, list):
        return True
    parsed_messages = _try_parse_langchain_message_dicts(messages)
    if parsed_messages is not None:
        for message in parsed_messages:
            if _message_is_unreplayable(
                message,
                require_assistant_response_id=require_assistant_response_id,
            ):
                return True
        return False
    for message in messages:
        if _message_is_unreplayable(
            message,
            require_assistant_response_id=require_assistant_response_id,
        ):
            return True
    return False


def _message_is_unreplayable(
    message: object,
    *,
    require_assistant_response_id: bool,
) -> bool:
    if isinstance(message, _LANGCHAIN_MESSAGE_TYPES):
        if _content_is_unreplayable(message.content):
            return True
        if require_assistant_response_id and isinstance(message, AIMessage):
            return extract_response_id(message) is None
        return False

    if not isinstance(message, dict):
        return True

    payload = _message_payload_dict(message)
    message_type = str(payload.get("type") or message.get("type") or "").strip().lower()
    if message_type in _UNSAFE_RESPONSE_ITEM_TYPES:
        return True

    if _content_is_unreplayable(payload.get("content")):
        return True

    if require_assistant_response_id and _is_assistant_message_dict(message):
        return extract_response_id(message) is None
    return False


def _content_is_unreplayable(content: object) -> bool:
    if content is None:
        return False
    if isinstance(content, str):
        return False
    if not isinstance(content, list):
        return True
    for block in content:
        if not isinstance(block, dict):
            return True
        block_type = str(block.get("type") or "").strip().lower()
        if not block_type:
            return True
        if block_type in _UNSAFE_RESPONSE_ITEM_TYPES:
            return True
        if (
            block_type not in _SAFE_CONTENT_BLOCK_TYPES
            and block_type not in _TEXT_BLOCK_TYPES
        ):
            return True
    return False


def _is_assistant_message_dict(message: dict[str, Any]) -> bool:
    payload = _message_payload_dict(message)
    role = str(payload.get("role") or "").strip().lower()
    if role == "assistant":
        return True
    message_type = str(payload.get("type") or message.get("type") or "").strip().lower()
    return message_type in {"ai", "assistant"}


def _message_payload_dict(message: dict[str, Any]) -> dict[str, Any]:
    """将字典形态的消息规范化为 payload 风格字典。"""
    data = message.get("data")
    if isinstance(data, dict):
        return data
    return message


def _try_parse_langchain_message_dicts(
    messages: list[object],
) -> Sequence[object] | None:
    if not messages:
        return []
    if not all(isinstance(message, dict) for message in messages):
        return None
    message_dicts = [message for message in messages if isinstance(message, dict)]
    try:
        parsed = messages_from_dict(message_dicts)
    except Exception:
        return None
    return parsed if len(parsed) == len(message_dicts) else None
