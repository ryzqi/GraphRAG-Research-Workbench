from __future__ import annotations

import logging
from time import perf_counter
import uuid

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import set_request_id

logger = logging.getLogger(__name__)


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = Headers(scope=scope).get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)
        started_at = perf_counter()
        response_started = False

        try:
            async def send_with_request_id(message: Message) -> None:
                nonlocal response_started

                if message["type"] == "http.response.start":
                    response_started = True
                    raw_headers = list(message.get("headers", []))
                    raw_headers = [
                        (name, value)
                        for name, value in raw_headers
                        if name.lower() != b"x-request-id"
                    ]
                    raw_headers.append(
                        (b"x-request-id", request_id.encode("latin-1"))
                    )
                    message = {**message, "headers": raw_headers}
                    logger.info(
                        "HTTP request completed",
                        extra=self._build_log_extra(
                            scope,
                            started_at,
                            status_code=message["status"],
                        ),
                    )

                await send(message)

            await self.app(scope, receive, send_with_request_id)
        except Exception:
            if response_started:
                raise
            logger.exception(
                "HTTP request failed",
                extra=self._build_log_extra(scope, started_at),
            )
            raise
        finally:
            set_request_id(None)

    @staticmethod
    def _build_log_extra(
        scope: Scope,
        started_at: float,
        *,
        status_code: int | None = None,
    ) -> dict[str, object]:
        query_string = scope.get("query_string", b"")
        query = (
            query_string.decode("latin-1")
            if isinstance(query_string, bytes) and query_string
            else None
        )
        client = scope.get("client")
        client_ip = client[0] if isinstance(client, tuple) and client else None
        extra: dict[str, object] = {
            "method": scope.get("method"),
            "path": scope.get("path"),
            "query": query,
            "client_ip": client_ip,
            "duration_ms": int((perf_counter() - started_at) * 1000),
        }
        if status_code is not None:
            extra["status_code"] = status_code
        return extra
