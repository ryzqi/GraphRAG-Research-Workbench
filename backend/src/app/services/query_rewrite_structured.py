from __future__ import annotations

import json
import re
from pydantic import BaseModel, ValidationError
def _extract_structured_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            for key in ("text", "content"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    chunks.append(raw.strip())
                    break
        return "\n".join(chunks).strip()
    return ""


def _debug_preview(value: object, *, limit: int = 1600) -> str:
    if isinstance(value, BaseModel):
        serializable: object = value.model_dump(mode="json")
    else:
        serializable = value
    try:
        rendered = json.dumps(serializable, ensure_ascii=False, default=str)
    except TypeError:
        rendered = repr(serializable)
    rendered = rendered.strip()
    if len(rendered) <= limit:
        return rendered
    return f"{rendered[:limit]}…"


def _looks_like_json_object_key(raw: str, start: int) -> bool:
    if start >= len(raw) or raw[start] != '"':
        return False

    i = start + 1
    escaped = False
    while i < len(raw):
        ch = raw[i]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            i += 1
            while i < len(raw) and raw[i].isspace():
                i += 1
            return i < len(raw) and raw[i] == ":"
        i += 1
    return False


def _repair_missing_array_object_start(raw: str) -> str | None:
    """修复数组对象项丢失起始 `{` 的近似 JSON 漂移。"""

    result: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    just_closed_object_in_array = False
    pending_array_item_after_comma = False
    changed = False

    for index, ch in enumerate(raw):
        if pending_array_item_after_comma:
            if ch.isspace():
                result.append(ch)
                continue
            if ch == '"' and _looks_like_json_object_key(raw, index):
                result.append("{")
                stack.append("{")
                changed = True
            pending_array_item_after_comma = False

        result.append(ch)

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            just_closed_object_in_array = False
            continue
        if ch == "{":
            stack.append("{")
            just_closed_object_in_array = False
            continue
        if ch == "[":
            stack.append("[")
            just_closed_object_in_array = False
            continue
        if ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
            just_closed_object_in_array = bool(stack and stack[-1] == "[")
            continue
        if ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
            just_closed_object_in_array = False
            continue
        if ch == ",":
            if just_closed_object_in_array:
                pending_array_item_after_comma = True
            just_closed_object_in_array = False
            continue
        if not ch.isspace():
            just_closed_object_in_array = False

    if not changed:
        return None
    return "".join(result)


def _repair_common_malformed_json(raw: str) -> str | None:
    """修复部分模型在 raw structured 文本里常见的近似 JSON 漂移。"""

    repaired = re.sub(r'(?<=\[)\s*"(?=\{)', "", raw)
    repaired = re.sub(r'(?<=,)\s*"(?=\{)', "", repaired)
    repaired = re.sub(r'}\s*,\s*"\s*}\s*,\s*(?=\{)', "},", repaired)
    repaired_array_object_start = _repair_missing_array_object_start(repaired)
    if repaired_array_object_start is not None:
        repaired = repaired_array_object_start
    if repaired == raw:
        return None
    return repaired


def _coerce_schema_from_json_like(
    *,
    value: object,
    schema: type[BaseModel],
) -> tuple[BaseModel | None, str | None]:
    if isinstance(value, schema):
        return value, None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, "empty_structured_response"

        candidates = [raw]
        repaired = _repair_common_malformed_json(raw)
        if repaired and repaired not in candidates:
            candidates.append(repaired)

        for candidate in candidates:
            try:
                return schema.model_validate_json(candidate), None
            except ValidationError:
                try:
                    value = json.loads(candidate)
                except (TypeError, ValueError):
                    continue
                try:
                    return schema.model_validate(value), None
                except ValidationError:
                    continue
        return None, "invalid_schema"
    try:
        return schema.model_validate(value), None
    except ValidationError:
        return None, "invalid_schema"


def _extract_tool_call_payload(raw: object) -> tuple[object | None, str | None]:
    # LangChain 会把 provider 的函数调用结果放进 tool_calls，
    # 也可能在参数解析失败时放进 invalid_tool_calls。两者都属于同一层
    # transport payload，优先在这里统一提取，避免上层业务再做 provider 特判。
    def _extract_from_langchain_tool_calls(
        calls: object,
    ) -> tuple[object | None, str | None]:
        if not isinstance(calls, list) or not calls:
            return None, None
        if len(calls) > 1:
            return None, "multiple_structured_outputs"
        call = calls[0]
        if not isinstance(call, dict):
            return None, None
        if "args" in call:
            return call.get("args"), None
        function = call.get("function")
        if isinstance(function, dict) and "arguments" in function:
            return function.get("arguments"), None
        return None, None

    tool_payload, tool_payload_error = _extract_from_langchain_tool_calls(
        getattr(raw, "tool_calls", None)
    )
    if tool_payload is not None or tool_payload_error is not None:
        return tool_payload, tool_payload_error

    invalid_tool_payload, invalid_tool_payload_error = (
        _extract_from_langchain_tool_calls(getattr(raw, "invalid_tool_calls", None))
    )
    if invalid_tool_payload is not None or invalid_tool_payload_error is not None:
        return invalid_tool_payload, invalid_tool_payload_error

    content = getattr(raw, "content", None)
    if isinstance(content, list) and content:
        content_payloads: list[object] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip().lower()
            if block_type not in {"tool_use", "tool_call"}:
                continue
            for key in ("input", "args"):
                if key in block:
                    content_payloads.append(block.get(key))
                    break
        if len(content_payloads) > 1:
            return None, "multiple_structured_outputs"
        if content_payloads:
            return content_payloads[0], None

    additional_kwargs = getattr(raw, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        openai_tool_calls = additional_kwargs.get("tool_calls")
        if isinstance(openai_tool_calls, list) and openai_tool_calls:
            if len(openai_tool_calls) > 1:
                return None, "multiple_structured_outputs"
            call = openai_tool_calls[0]
            if isinstance(call, dict):
                function = call.get("function")
                if isinstance(function, dict) and "arguments" in function:
                    return function.get("arguments"), None
    return None, None


def coerce_structured_result_payload(
    *,
    result: object,
    schema: type[BaseModel],
) -> tuple[BaseModel | None, str | None]:
    if result is None:
        return None, "empty_structured_response"

    if isinstance(result, schema):
        return result, None

    if isinstance(result, dict):
        parsed = result.get("parsed")
        if isinstance(parsed, schema):
            return parsed, None
        if parsed is not None:
            try:
                return schema.model_validate(parsed), None
            except ValidationError:
                pass

        raw = result.get("raw")
        tool_payload, tool_payload_error = _extract_tool_call_payload(raw)
        tool_payload_invalid = False
        if tool_payload_error is not None:
            return None, tool_payload_error
        if tool_payload is not None:
            payload, reason = _coerce_schema_from_json_like(
                value=tool_payload,
                schema=schema,
            )
            if payload is not None or reason != "invalid_schema":
                return payload, reason
            tool_payload_invalid = True
        raw_content = _extract_structured_text(getattr(raw, "content", raw))
        if raw_content:
            return _coerce_schema_from_json_like(value=raw_content, schema=schema)
        if tool_payload_invalid:
            return None, "invalid_schema"

        try:
            return schema.model_validate(result), None
        except ValidationError:
            parsing_error = result.get("parsing_error")
            if parsing_error is not None:
                return None, "invalid_schema"
            return None, "empty_structured_response"

    raw_content = _extract_structured_text(getattr(result, "content", result))
    if raw_content:
        return _coerce_schema_from_json_like(value=raw_content, schema=schema)

    return _coerce_schema_from_json_like(value=result, schema=schema)


def _structured_result_debug_snapshot(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        return {
            "result_type": type(result).__name__,
            "result_preview": _debug_preview(result),
        }

    raw = result.get("raw")
    tool_payload, tool_payload_error = _extract_tool_call_payload(raw)
    return {
        "result_type": "dict",
        "parsed_type": type(result.get("parsed")).__name__
        if result.get("parsed") is not None
        else None,
        "parsed_preview": _debug_preview(result.get("parsed")),
        "parsing_error_type": (
            type(result.get("parsing_error")).__name__
            if result.get("parsing_error") is not None
            else None
        ),
        "parsing_error_preview": _debug_preview(result.get("parsing_error")),
        "raw_type": type(raw).__name__ if raw is not None else None,
        "raw_content_preview": _debug_preview(getattr(raw, "content", None)),
        "raw_tool_calls_preview": _debug_preview(getattr(raw, "tool_calls", None)),
        "raw_additional_kwargs_preview": _debug_preview(
            getattr(raw, "additional_kwargs", None)
        ),
        "tool_payload_error": tool_payload_error,
        "tool_payload_preview": _debug_preview(tool_payload),
    }
