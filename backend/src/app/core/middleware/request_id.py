from __future__ import annotations

import logging
from time import perf_counter
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import set_request_id

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)
        started_at = perf_counter()

        try:
            response: Response = await call_next(request)
        except Exception:
            logger.exception(
                "HTTP request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query or None,
                    "client_ip": request.client.host if request.client else None,
                    "duration_ms": int((perf_counter() - started_at) * 1000),
                },
            )
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "HTTP request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query or None,
                    "status_code": response.status_code,
                    "client_ip": request.client.host if request.client else None,
                    "duration_ms": int((perf_counter() - started_at) * 1000),
                },
            )
            return response
        finally:
            set_request_id(None)
