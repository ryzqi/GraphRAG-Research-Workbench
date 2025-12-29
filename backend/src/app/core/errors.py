from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    HTTP_ERROR = "http_error"
    INTERNAL_ERROR = "internal_error"
    NOT_FOUND = "not_found"


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None


def build_error_response(
    *,
    code: str,
    message: str,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {"code": code, "message": message},
    }
    if details is not None:
        payload["error"]["details"] = details
    if request_id:
        payload["request_id"] = request_id
    return payload

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(
                code=exc.code,
                message=exc.message,
                request_id=get_request_id(),
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=build_error_response(
                code=ErrorCode.VALIDATION_ERROR.value,
                message="参数校验失败",
                request_id=get_request_id(),
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(request: Request, exc: StarletteHTTPException):
        code = ErrorCode.NOT_FOUND.value if exc.status_code == 404 else ErrorCode.HTTP_ERROR.value
        message = "资源不存在" if exc.status_code == 404 else (exc.detail or "请求错误")
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(code=code, message=str(message), request_id=get_request_id()),
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled_error(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content=build_error_response(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="服务器内部错误",
                request_id=get_request_id(),
            ),
        )
