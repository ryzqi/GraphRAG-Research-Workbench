from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_request_id, set_request_id
from app.core.middleware.request_id import RequestIdMiddleware


class _HttpHarness:
    def __init__(
        self,
        *,
        path: str,
        headers: list[tuple[bytes, bytes]] | None = None,
        spec_version: str = "2.4",
        disconnect_after_first_body: bool = False,
    ) -> None:
        self.messages: list[dict[str, Any]] = []
        self._path = path
        self._headers = headers or []
        self._spec_version = spec_version
        self._disconnect_after_first_body = disconnect_after_first_body
        self._request_sent = False
        self._disconnect = asyncio.Event()
        self._sent_first_body = False

    @property
    def scope(self) -> dict[str, Any]:
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": self._spec_version},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": self._path,
            "raw_path": self._path.encode("ascii"),
            "query_string": b"",
            "headers": list(self._headers),
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }

    async def receive(self) -> dict[str, Any]:
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        if self._disconnect_after_first_body:
            await self._disconnect.wait()
            return {"type": "http.disconnect"}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if (
            self._disconnect_after_first_body
            and message["type"] == "http.response.body"
            and message.get("body")
            and not self._sent_first_body
        ):
            self._sent_first_body = True
            self._disconnect.set()


async def _invoke_http_app(
    app: Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]],
    *,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    spec_version: str = "2.4",
    disconnect_after_first_body: bool = False,
) -> list[dict[str, Any]]:
    harness = _HttpHarness(
        path=path,
        headers=headers,
        spec_version=spec_version,
        disconnect_after_first_body=disconnect_after_first_body,
    )
    await app(harness.scope, harness.receive, harness.send)
    return harness.messages


def _response_start_headers(messages: list[dict[str, Any]]) -> dict[bytes, bytes]:
    start_message = next(message for message in messages if message["type"] == "http.response.start")
    return dict(start_message.get("headers", []))


def _response_body_text(messages: list[dict[str, Any]]) -> str:
    chunks = [
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    ]
    return b"".join(chunks).decode("utf-8")


def test_request_id_header_is_added_to_success_response() -> None:
    async def _exercise() -> None:
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/ok")
        async def ok() -> PlainTextResponse:
            return PlainTextResponse("ok")

        messages = await _invoke_http_app(app, path="/ok")
        headers = _response_start_headers(messages)

        assert b"x-request-id" in headers
        assert headers[b"x-request-id"]
        assert get_request_id() is None

    asyncio.run(_exercise())


def test_request_id_middleware_is_native_asgi_middleware() -> None:
    assert not issubclass(RequestIdMiddleware, BaseHTTPMiddleware)


def test_request_id_header_reuses_client_supplied_value() -> None:
    async def _exercise() -> None:
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/ok")
        async def ok() -> PlainTextResponse:
            return PlainTextResponse("ok")

        messages = await _invoke_http_app(
            app,
            path="/ok",
            headers=[(b"x-request-id", b"req-123")],
        )
        headers = _response_start_headers(messages)

        assert headers[b"x-request-id"] == b"req-123"
        assert get_request_id() is None

    asyncio.run(_exercise())


def test_request_id_is_available_to_exception_handler_without_failure_log(
    caplog,
) -> None:
    async def _exercise() -> None:
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.exception_handler(RuntimeError)
        async def handle_runtime_error(
            request: Request,
            exc: RuntimeError,
        ) -> JSONResponse:
            del request, exc
            return JSONResponse(
                {"request_id": get_request_id()},
                status_code=500,
            )

        @app.get("/boom")
        async def boom() -> None:
            raise RuntimeError("boom")

        with caplog.at_level(logging.ERROR):
            messages = await _invoke_http_app(
                app,
                path="/boom",
                headers=[(b"x-request-id", b"req-exc")],
            )

        payload = json.loads(_response_body_text(messages))
        headers = _response_start_headers(messages)

        assert payload["request_id"] == "req-exc"
        assert headers[b"x-request-id"] == b"req-exc"
        assert "HTTP request failed" not in caplog.text
        assert get_request_id() is None

    asyncio.run(_exercise())


def test_stream_disconnect_keeps_request_id_contract() -> None:
    async def _exercise() -> None:
        events: list[str] = []
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/stream")
        async def stream() -> StreamingResponse:
            async def body() -> Any:
                try:
                    yield b"one\n"
                    await asyncio.sleep(1)
                    yield b"two\n"
                except BaseException as exc:
                    events.append(f"body-exc:{type(exc).__name__}")
                    raise
                finally:
                    events.append("cleanup-start")
                    try:
                        await asyncio.sleep(0.05)
                        events.append("cleanup-ok")
                    except BaseException as exc:
                        events.append(f"cleanup-exc:{type(exc).__name__}")
                        raise

            return StreamingResponse(body(), media_type="text/plain")

        messages = await _invoke_http_app(
            app,
            path="/stream",
            spec_version="2.3",
            disconnect_after_first_body=True,
        )
        headers = _response_start_headers(messages)

        assert headers[b"x-request-id"]
        assert "cleanup-start" in events
        assert get_request_id() is None

    asyncio.run(_exercise())


def test_non_http_scope_passes_through_without_touching_request_id() -> None:
    async def _exercise() -> None:
        called: list[str] = []

        async def fake_app(scope, receive, send) -> None:
            del receive, send
            called.append(scope["type"])

        middleware = RequestIdMiddleware(fake_app)
        set_request_id(None)

        await middleware(
            {
                "type": "websocket",
                "asgi": {"version": "3.0"},
                "path": "/ws",
                "headers": [],
            },
            lambda: asyncio.sleep(0),
            lambda message: asyncio.sleep(0),
        )

        assert called == ["websocket"]
        assert get_request_id() is None

    asyncio.run(_exercise())
