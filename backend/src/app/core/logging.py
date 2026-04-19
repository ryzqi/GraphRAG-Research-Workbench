from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from typing import Any

_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
_run_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "run_id", default=None
)
_DEFAULT_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(message)s "
    "request_id=%(request_id)s run_id=%(run_id)s"
)
_NOISY_INFO_LOGGERS = ("httpx", "httpcore", "uvicorn.access")
_RECORD_RESERVED_KEYS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "request_id",
    "run_id",
}

# 敏感字段模式
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API Key / Token（常见格式）
    (
        re.compile(
            r"(api[_-]?key|token|secret|password|credential)[\"']?\s*[:=]\s*[\"']?[\w\-\.]+",
            re.I,
        ),
        r"\1=***REDACTED***",
    ),
    # Bearer Token
    (re.compile(r"Bearer\s+[\w\-\.]+", re.I), "Bearer ***REDACTED***"),
    # 邮箱地址
    (re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"), "***EMAIL***"),
    # 手机号（中国大陆）
    (re.compile(r"1[3-9]\d{9}"), "***PHONE***"),
    # 身份证号
    (re.compile(r"\d{17}[\dXx]"), "***ID_CARD***"),
]


def set_request_id(request_id: str | None) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def set_run_id(run_id: str | None) -> None:
    _run_id_ctx.set(run_id)


def get_run_id() -> str | None:
    return _run_id_ctx.get()


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        record.run_id = getattr(record, "run_id", None) or get_run_id() or "-"
        return True


class UnifiedFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original_args = record.args
        try:
            record.args = _redact_format_args(record.args)
            message = super().format(record)
        finally:
            record.args = original_args
        extras = _format_extra_fields(record)
        if extras:
            message = f"{message} {extras}"
        return redact(message)


def _normalize_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    text = str(level or "INFO").strip().upper()
    resolved = logging.getLevelName(text)
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def _format_log_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float)) or value is None:
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _redact_format_args(args: Any) -> Any:
    if isinstance(args, dict):
        return redact_dict(args)
    if isinstance(args, tuple):
        return tuple(_redact_structured_value(item) for item in args)
    if isinstance(args, list):
        return [_redact_structured_value(item) for item in args]
    return _redact_structured_value(args)


def _redact_structured_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return [_redact_structured_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_structured_value(item) for item in value)
    if isinstance(value, set):
        return {_redact_structured_value(item) for item in value}
    return value


def _format_extra_fields(record: logging.LogRecord) -> str:
    extra_parts: list[str] = []
    for key in sorted(record.__dict__):
        if key in _RECORD_RESERVED_KEYS or key.startswith("_"):
            continue
        value = _redact_structured_value(record.__dict__[key])
        extra_parts.append(f"{key}={_format_log_value(value)}")
    return " ".join(extra_parts)


def _configure_named_logger(name: str, *, level: int, propagate: bool = True) -> None:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = propagate
    logger.setLevel(level)


def configure_logging(level: str = "INFO") -> None:
    resolved_level = _normalize_level(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.NOTSET)
    handler.setFormatter(UnifiedFormatter(_DEFAULT_FORMAT))
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()
    root.setLevel(resolved_level)
    root.addHandler(handler)

    _configure_named_logger("uvicorn", level=logging.NOTSET)
    _configure_named_logger("uvicorn.error", level=logging.NOTSET)
    _configure_named_logger("celery", level=logging.NOTSET)
    _configure_named_logger("celery.task", level=logging.NOTSET)
    for name in _NOISY_INFO_LOGGERS:
        _configure_named_logger(name, level=logging.WARNING)


def redact(value: Any) -> Any:
    """日志脱敏：屏蔽敏感字段。"""
    if not isinstance(value, str):
        return value
    result = value
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_dict(
    data: dict[str, Any], sensitive_keys: set[str] | None = None
) -> dict[str, Any]:
    """对字典中的敏感键值进行脱敏。"""
    if sensitive_keys is None:
        sensitive_keys = {
            "api_key",
            "token",
            "secret",
            "password",
            "credential",
            "authorization",
        }
    result: dict[str, Any] = {}
    for k, v in data.items():
        if k.lower() in sensitive_keys:
            result[k] = "***REDACTED***"
        elif isinstance(v, dict):
            result[k] = redact_dict(v, sensitive_keys)
        elif isinstance(v, list):
            result[k] = [_redact_structured_value(item) for item in v]
        elif isinstance(v, tuple):
            result[k] = tuple(_redact_structured_value(item) for item in v)
        elif isinstance(v, set):
            result[k] = {_redact_structured_value(item) for item in v}
        elif isinstance(v, str):
            result[k] = redact(v)
        else:
            result[k] = v
    return result
