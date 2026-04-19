import logging

from app.core import logging as app_logging


def _build_record() -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logging",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling api with token=%s user=%s",
        args=(
            "sk-secret12345",
            {"email": "a@b.com", "nested": {"api_key": "k-xyz"}},
        ),
        exc_info=None,
    )
    record.payload = {"api_key": "p-123", "nested": {"email": "b@c.com"}}
    return record


def test_context_filter_only_sets_context_fields() -> None:
    record = _build_record()

    assert app_logging.ContextFilter().filter(record) is True
    assert record.request_id == "-"
    assert record.run_id == "-"
    assert record.msg == "calling api with token=%s user=%s"
    assert record.args == (
        "sk-secret12345",
        {"email": "a@b.com", "nested": {"api_key": "k-xyz"}},
    )
    assert record.payload == {"api_key": "p-123", "nested": {"email": "b@c.com"}}


def test_unified_formatter_redacts_message_and_extra_fields() -> None:
    record = _build_record()

    app_logging.ContextFilter().filter(record)
    rendered = app_logging.UnifiedFormatter(app_logging._DEFAULT_FORMAT).format(record)

    assert "sk-secret12345" not in rendered
    assert "a@b.com" not in rendered
    assert "k-xyz" not in rendered
    assert "p-123" not in rendered
    assert "b@c.com" not in rendered
    assert "***REDACTED***" in rendered
    assert "***EMAIL***" in rendered


def test_unified_formatter_redacts_authorization_in_structured_values() -> None:
    record = logging.LogRecord(
        name="test.logging",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="payload=%s",
        args=([{"authorization": "plain-secret-token"}],),
        exc_info=None,
    )
    record.payload = [{"authorization": "plain-secret-token"}]

    app_logging.ContextFilter().filter(record)
    rendered = app_logging.UnifiedFormatter(app_logging._DEFAULT_FORMAT).format(record)

    assert "plain-secret-token" not in rendered
    assert rendered.count("***REDACTED***") >= 2
