"""网页搜索工具共享纯函数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import httpx

try:
    import tavily as _tavily
except Exception:  # pragma: no cover - 依赖缺失时不阻断导入
    _tavily = None

BadRequestError = getattr(_tavily, "BadRequestError", ())
ForbiddenError = getattr(_tavily, "ForbiddenError", ())
InvalidAPIKeyError = getattr(_tavily, "InvalidAPIKeyError", ())
TavilyTimeoutError = getattr(_tavily, "TimeoutError", ())
UsageLimitExceededError = getattr(_tavily, "UsageLimitExceededError", ())


@dataclass(slots=True)
class TavilyCallContext:
    query: str | None
    parameters: dict[str, Any]
    cache_key: str | None = None


def extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def format_tavily_error(
    exc: Exception,
    *,
    code_prefix: str,
    default_message: str,
) -> dict[str, Any]:
    status_code = extract_status_code(exc)
    code = f"{code_prefix}_UPSTREAM_ERROR"
    message = default_message
    retryable = False

    if isinstance(exc, UsageLimitExceededError):
        code = f"{code_prefix}_RATE_LIMITED"
        message = "请求过于频繁或额度不足，请稍后重试"
        retryable = True
    elif isinstance(exc, InvalidAPIKeyError) or (
        isinstance(exc, RuntimeError) and "WEB_SEARCH_API_KEY" in str(exc)
    ):
        code = f"{code_prefix}_AUTH_ERROR"
        message = "WEB_SEARCH_API_KEY 无效或未配置"
    elif isinstance(exc, ForbiddenError):
        code = f"{code_prefix}_FORBIDDEN"
        message = "请求被拒绝，可能需要提升权限"
    elif isinstance(exc, BadRequestError):
        code = f"{code_prefix}_BAD_REQUEST"
        message = "请求参数错误"
    elif isinstance(exc, TavilyTimeoutError) or isinstance(exc, httpx.TimeoutException):
        code = f"{code_prefix}_TIMEOUT"
        message = "请求超时，请稍后重试"
        retryable = True
    elif status_code == 402:
        code = f"{code_prefix}_PAYMENT_REQUIRED"
        message = "Tavily 返回 402 Payment Required，可能余额不足或套餐到期"
    elif status_code == 429:
        code = f"{code_prefix}_RATE_LIMITED"
        message = "请求过于频繁，请稍后重试"
        retryable = True
    elif status_code in {401, 403}:
        code = f"{code_prefix}_AUTH_ERROR"
        message = "鉴权失败，请检查 WEB_SEARCH_API_KEY"
    elif status_code is not None and status_code >= 500:
        retryable = True

    detail = str(exc).strip()
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if status_code is not None:
        error["status_code"] = status_code
    if detail:
        error["detail"] = detail[:300]
    return error


def format_validation_error(code_prefix: str, message: str) -> dict[str, Any]:
    return {
        "code": f"{code_prefix}_BAD_REQUEST",
        "message": message,
        "retryable": False,
    }


def normalize_domains(domains: Iterable[str] | None) -> list[str] | None:
    if not domains:
        return None
    normalized = [d.strip() for d in domains if d and d.strip()]
    return normalized or None


def filter_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None and v != []}


def format_search_type(search_type: str) -> str:
    if search_type in {"news", "finance"}:
        return search_type
    return "general"


def should_degrade_search(payload: dict[str, Any], exc: Exception) -> bool:
    if (
        payload.get("search_depth") != "advanced"
        and not payload.get("include_raw_content")
        and not payload.get("include_images")
        and not payload.get("include_image_descriptions")
    ):
        return False
    if isinstance(exc, TavilyTimeoutError) or isinstance(exc, httpx.TimeoutException):
        return True
    status_code = extract_status_code(exc)
    return status_code in {408, 429, 500, 502, 503, 504}


def degrade_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    degraded = dict(payload)
    degraded["search_depth"] = "basic"
    degraded["include_raw_content"] = False
    degraded["include_images"] = False
    degraded["include_image_descriptions"] = False
    degraded["include_answer"] = False
    return degraded


def normalize_results(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in items:
        results.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
                "published_at": item.get("published_date") or item.get("published_at"),
                "raw_content": item.get("raw_content"),
                "images": item.get("images"),
                "favicon": item.get("favicon"),
                "source": item.get("source") or "tavily",
            }
        )
    return results


def build_output(
    *,
    context: TavilyCallContext,
    results: list[dict[str, Any]],
    elapsed_ms: int,
    cache_hit: bool,
    total_found: int | None = None,
    usage: dict[str, Any] | None = None,
    request_id: str | None = None,
    answer: str | None = None,
    report: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "query": context.query,
        "parameters": context.parameters,
        "total_found": total_found if total_found is not None else len(results),
        "results": results,
        "error": error,
        "usage": usage,
        "request_id": request_id,
        "elapsed_ms": elapsed_ms,
        "cache_hit": cache_hit,
    }
    if answer:
        output["answer"] = answer
    if report:
        output["report"] = report
    return output
