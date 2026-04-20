from __future__ import annotations

from types import SimpleNamespace

from app.services.general_chat_service_streaming_ops import _sanitize_stream_delta_dicts
from app.services.streaming import DeltaKind, StreamDelta


def test_stream_delta_payloads_are_sanitized_before_sse_emit() -> None:
    deltas = [
        StreamDelta(
            kind=DeltaKind.ANSWER,
            content="联系 alice@example.com，电话 +86 13800138000，身份证 110101199001011234",
        ),
        StreamDelta(
            kind=DeltaKind.TOOL_CALL,
            tool_name="send_email",
            tool_args={"token": "secret-token", "email": "alice@example.com"},
        ),
    ]

    sanitized = _sanitize_stream_delta_dicts(
        deltas=deltas,
        settings=SimpleNamespace(
            pii_middleware_enabled=True,
            pii_redaction_strategy="redact",
        ),
    )

    answer_delta = sanitized[0]
    tool_delta = sanitized[1]

    assert "alice@example.com" not in answer_delta["content"]
    assert "13800138000" not in answer_delta["content"]
    assert "110101199001011234" not in answer_delta["content"]
    assert "[REDACTED_EMAIL]" in answer_delta["content"]
    assert "[REDACTED_PHONE_NUMBER]" in answer_delta["content"]
    assert "[REDACTED_ID_CARD]" in answer_delta["content"]
    assert tool_delta["tool_args"]["token"] == "***REDACTED***"
    assert tool_delta["tool_args"]["email"] == "[REDACTED_EMAIL]"
