from __future__ import annotations

import io
import logging
import sys
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.logging import configure_logging, set_request_id, set_run_id
from app.core.middleware.request_id import RequestIdMiddleware


@pytest.fixture(autouse=True)
def restore_logging_state() -> Iterator[None]:
    root = logging.getLogger()
    original_root_handlers = root.handlers[:]
    original_root_level = root.level

    named_logger_names = (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "celery",
        "celery.task",
    )
    original_named: dict[str, tuple[list[logging.Handler], int, bool]] = {}
    for name in named_logger_names:
        logger = logging.getLogger(name)
        original_named[name] = (logger.handlers[:], logger.level, logger.propagate)

    try:
        yield
    finally:
        set_request_id(None)
        set_run_id(None)

        root.handlers[:] = original_root_handlers
        root.setLevel(original_root_level)

        for name, (handlers, level, propagate) in original_named.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.setLevel(level)
            logger.propagate = propagate


def test_configure_logging_replaces_existing_root_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    stale_stream = io.StringIO()
    root.handlers[:] = [logging.StreamHandler(stale_stream)]
    root.setLevel(logging.WARNING)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    configure_logging("DEBUG")
    set_request_id("req-123")
    set_run_id("run-456")

    logging.getLogger("tests.logging").debug("hello unified logging")

    output = stream.getvalue()
    assert "hello unified logging" in output
    assert "request_id=req-123" in output
    assert "run_id=run-456" in output
    assert stale_stream.getvalue() == ""


def test_configure_logging_redacts_percent_style_args_and_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    root.handlers[:] = []
    root.setLevel(logging.NOTSET)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    configure_logging("INFO")

    logging.getLogger("tests.logging").warning(
        "token=%s",
        "sk-secret-123",
        extra={
            "error": "api_key=plain-secret",
            "contact": "alice@example.com",
        },
    )

    output = stream.getvalue()
    assert "sk-secret-123" not in output
    assert "plain-secret" not in output
    assert "alice@example.com" not in output
    assert "***REDACTED***" in output
    assert "error=" in output
    assert "contact=" in output


def test_request_id_middleware_logs_request_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    root.handlers[:] = []
    root.setLevel(logging.NOTSET)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    configure_logging("INFO")

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def _ping() -> JSONResponse:
        return JSONResponse({"ok": True})

    with TestClient(app) as client:
        response = client.get("/ping", headers={"X-Request-ID": "req-from-client"})

    output = stream.getvalue()
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-from-client"
    assert "req-from-client" in output
    assert "GET" in output
    assert "/ping" in output
    assert "200" in output


def test_celery_logging_uses_app_log_level_as_single_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    root.handlers[:] = [logging.StreamHandler(io.StringIO())]
    root.setLevel(logging.WARNING)

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    from app.worker.celery_app import configure_celery_logging

    configure_celery_logging("DEBUG")
    logging.getLogger("celery.tests").debug("celery debug message")

    output = stream.getvalue()
    assert "celery debug message" in output
    assert "DEBUG" in output
