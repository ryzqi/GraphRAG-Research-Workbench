from __future__ import annotations

import contextvars
import logging
import re
from typing import Any

_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
_run_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "run_id", default=None
)

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
        record.request_id = get_request_id() or "-"
        record.run_id = get_run_id() or "-"
        # 对日志消息进行脱敏
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "request_id=%(request_id)s run_id=%(run_id)s"
        ),
    )

    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(ContextFilter())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


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
        elif isinstance(v, str):
            result[k] = redact(v)
        else:
            result[k] = v
    return result
