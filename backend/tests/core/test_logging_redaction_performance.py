import logging

from app.core import logging as app_logging


def _build_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logging",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling api with token=%s",
        args=("sk-secret12345",),
        exc_info=None,
    )


def test_unified_formatter_redacts_message_once_per_record(monkeypatch) -> None:
    original_redact = app_logging.redact
    calls: list[str] = []

    def counting_redact(value):
        if isinstance(value, str):
            calls.append(value)
        return original_redact(value)

    monkeypatch.setattr(app_logging, "redact", counting_redact)

    record = _build_record()
    app_logging.ContextFilter().filter(record)
    rendered = app_logging.UnifiedFormatter(app_logging._DEFAULT_FORMAT).format(record)

    assert "sk-secret12345" not in rendered
    assert len(calls) == 1
