"""PII 中间件与本地输出脱敏辅助。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any, Literal, cast

from langchain.agents.middleware import PIIMiddleware
from langchain.agents.middleware.pii import apply_strategy

from app.core.settings import Settings

PHONE_NUMBER_PATTERN = r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"
ID_CARD_PATTERN = r"\b\d{17}[\dXx]\b"
EMAIL_PATTERN = r"[\w\.-]+@[\w\.-]+\.\w+"
_SENSITIVE_EXPORT_KEYS = frozenset(
    {
        "api_key",
        "token",
        "secret",
        "password",
        "credential",
        "authorization",
    }
)
_SECRET_TEXT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(api[_-]?key|token|secret|password|credential)[\"']?\s*[:=]\s*[\"']?[\w\-\.]+",
            re.I,
        ),
        r"\1=***REDACTED***",
    ),
    (re.compile(r"Bearer\s+[\w\-\.]+", re.I), "Bearer ***REDACTED***"),
)

PiiStrategy = Literal["redact", "mask", "hash", "block"]


def build_pii_middleware(*, settings: Settings) -> list[Any]:
    """按 settings 构建面向输出的 PII middleware。"""
    if not bool(getattr(settings, "pii_middleware_enabled", True)):
        return []

    strategy = str(getattr(settings, "pii_redaction_strategy", "redact") or "redact")
    apply_to_tool_results = bool(
        getattr(settings, "pii_apply_to_tool_results", False)
    )
    common_kwargs = {
        "strategy": strategy,
        "apply_to_input": False,
        "apply_to_output": True,
        "apply_to_tool_results": apply_to_tool_results,
    }
    return [
        PIIMiddleware("email", **common_kwargs),
        PIIMiddleware(
            "phone_number",
            detector=PHONE_NUMBER_PATTERN,
            **common_kwargs,
        ),
        PIIMiddleware(
            "id_card",
            detector=ID_CARD_PATTERN,
            **common_kwargs,
        ),
    ]


def _apply_text_strategy(
    text: str,
    *,
    enabled: bool,
    strategy: PiiStrategy,
) -> str:
    if not enabled:
        return text

    transformed = text
    for pii_type, pattern in (
        ("email", EMAIL_PATTERN),
        ("id_card", ID_CARD_PATTERN),
        ("phone_number", PHONE_NUMBER_PATTERN),
    ):
        detector = PIIMiddleware(
            pii_type,
            detector=pattern,
            strategy=strategy,
            apply_to_input=False,
            apply_to_output=True,
        ).detector
        matches = detector(transformed)
        if matches:
            transformed = apply_strategy(transformed, matches, strategy)

    for pattern, replacement in _SECRET_TEXT_REPLACEMENTS:
        transformed = pattern.sub(replacement, transformed)
    return transformed


def sanitize_pii_text(
    text: str,
    *,
    enabled: bool,
    strategy: PiiStrategy = "redact",
) -> str:
    """对纯文本执行与 agent middleware 对齐的 PII 策略。"""
    return _apply_text_strategy(text, enabled=enabled, strategy=strategy)


def sanitize_pii_value(
    value: Any,
    *,
    enabled: bool = True,
    strategy: PiiStrategy = "redact",
) -> Any:
    """递归脱敏结构化导出内容中的文本与敏感字段。"""
    if not enabled:
        return value
    if isinstance(value, str):
        return sanitize_pii_text(value, enabled=enabled, strategy=strategy)
    if isinstance(value, Mapping):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_EXPORT_KEYS:
                sanitized[key] = "***REDACTED***"
                continue
            sanitized[key] = sanitize_pii_value(
                item,
                enabled=enabled,
                strategy=strategy,
            )
        return sanitized
    if isinstance(value, list):
        return [
            sanitize_pii_value(item, enabled=enabled, strategy=strategy)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            sanitize_pii_value(item, enabled=enabled, strategy=strategy)
            for item in value
        )
    if isinstance(value, set):
        return {
            sanitize_pii_value(item, enabled=enabled, strategy=strategy)
            for item in value
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [
            sanitize_pii_value(item, enabled=enabled, strategy=strategy)
            for item in value
        ]
    return value


def sanitize_export_text(
    text: str,
    *,
    enabled: bool,
    strategy: PiiStrategy = "redact",
) -> str:
    """按导出开关对文本做脱敏。"""
    sanitized = sanitize_pii_value(text, enabled=enabled, strategy=strategy)
    return sanitized if isinstance(sanitized, str) else text


def sanitize_with_settings(value: Any, *, settings: Any) -> Any:
    """按 settings 驱动的统一 PII 输出脱敏。"""
    strategy = cast(
        PiiStrategy,
        str(getattr(settings, "pii_redaction_strategy", "redact") or "redact"),
    )
    enabled = bool(getattr(settings, "pii_middleware_enabled", True))
    return sanitize_pii_value(value, enabled=enabled, strategy=strategy)
