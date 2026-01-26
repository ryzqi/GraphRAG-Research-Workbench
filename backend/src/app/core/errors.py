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
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # Ensure `str(AppError)` is meaningful (dataclass doesn't call Exception.__init__).
        Exception.__init__(self, f"{self.code}: {self.message}")


def not_found(
    message: str = "资源不存在",
    *,
    code: str | None = None,
    details: dict[str, Any] | None = None,
) -> AppError:
    """构造 404 错误（统一错误体输出）。"""
    return AppError(
        code=code or ErrorCode.NOT_FOUND.value,
        message=message,
        status_code=404,
        details=details,
    )


def bad_request(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> AppError:
    """构造 400 错误（统一错误体输出）。"""
    return AppError(code=code, message=message, status_code=400, details=details)


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


def _apply_cors_headers(request: Request, response: JSONResponse) -> JSONResponse:
    """为异常响应补齐 CORS 头，避免前端把 4xx/5xx 误判为 CORS 失败。"""
    origin = request.headers.get("origin")
    if not origin:
        return response

    allowed = get_settings().app_cors_allow_origins
    if "*" in allowed or origin in allowed:
        # 由于主应用启用了 allow_credentials=True，这里不直接返回 "*"。
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")

        vary = response.headers.get("Vary")
        if vary:
            parts = [p.strip() for p in vary.split(",") if p.strip()]
            if "Origin" not in parts:
                response.headers["Vary"] = ", ".join([*parts, "Origin"])
        else:
            response.headers["Vary"] = "Origin"

    return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError):
        res = JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(
                code=exc.code,
                message=exc.message,
                request_id=get_request_id(),
                details=exc.details,
            ),
        )
        return _apply_cors_headers(request, res)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        res = JSONResponse(
            status_code=422,
            content=build_error_response(
                code=ErrorCode.VALIDATION_ERROR.value,
                message="参数校验失败",
                request_id=get_request_id(),
                details={"errors": exc.errors()},
            ),
        )
        return _apply_cors_headers(request, res)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(request: Request, exc: StarletteHTTPException):
        request_id = get_request_id()

        if isinstance(exc.detail, dict):
            raw_code = exc.detail.get("code")
            raw_message = exc.detail.get("message")
            code = (
                str(raw_code)
                if raw_code
                else (
                    ErrorCode.NOT_FOUND.value
                    if exc.status_code == 404
                    else ErrorCode.HTTP_ERROR.value
                )
            )
            message = (
                str(raw_message)
                if raw_message
                else ("资源不存在" if exc.status_code == 404 else "请求错误")
            )

            raw_details: Any = exc.detail.get("details")
            details: dict[str, Any] | None = None
            if raw_details is None:
                extra = {
                    k: v for k, v in exc.detail.items() if k not in {"code", "message"}
                }
                details = extra or None
            elif isinstance(raw_details, dict):
                details = raw_details
            else:
                details = {"detail": raw_details}

            res = JSONResponse(
                status_code=exc.status_code,
                content=build_error_response(
                    code=code,
                    message=message,
                    request_id=request_id,
                    details=details,
                ),
            )
            return _apply_cors_headers(request, res)

        if exc.status_code == 404 and isinstance(exc.detail, str):
            detail = exc.detail.strip()
            if detail and detail.lower() != "not found":
                res = JSONResponse(
                    status_code=exc.status_code,
                    content=build_error_response(
                        code=ErrorCode.NOT_FOUND.value,
                        message=detail,
                        request_id=request_id,
                    ),
                )
                return _apply_cors_headers(request, res)

        code = (
            ErrorCode.NOT_FOUND.value
            if exc.status_code == 404
            else ErrorCode.HTTP_ERROR.value
        )
        message = "资源不存在" if exc.status_code == 404 else (exc.detail or "请求错误")
        res = JSONResponse(
            status_code=exc.status_code,
            content=build_error_response(
                code=code,
                message=str(message),
                request_id=request_id,
            ),
        )
        return _apply_cors_headers(request, res)

    @app.exception_handler(Exception)
    async def _handle_unhandled_error(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        res = JSONResponse(
            status_code=500,
            content=build_error_response(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="服务器内部错误",
                request_id=get_request_id(),
            ),
        )
        return _apply_cors_headers(request, res)
