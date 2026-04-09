"""内置联网工具输出压缩。

目标：在不破坏 JSON 结构的前提下，对内置 web 工具输出做字段级压缩，
避免简单字符串截断导致下游无法再解析结构化结果。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .utils import DEFAULT_TOOL_OUTPUT_MAX_CHARS, truncate_tool_output

_ELLIPSIS = "…"


def compact_builtin_external_output(
    tool_name: str,
    output: object,
    max_chars: int = DEFAULT_TOOL_OUTPUT_MAX_CHARS,
) -> str:
    """压缩内置联网工具输出，并尽量保持为可解析 JSON。"""
    if max_chars <= 0:
        return "{}"

    payload = _parse_json_like(output)

    if tool_name == "web_search":
        text = _compact_web_search_output(payload, max_chars)
        if text is not None:
            return text
    if tool_name == "web_extract":
        text = _compact_web_extract_output(payload, max_chars)
        if text is not None:
            return text
    if tool_name == "jina_read":
        text = _compact_jina_read_output(payload, max_chars)
        if text is not None:
            return text

    fallback, _ = truncate_tool_output(_stringify(output), max_chars)
    return fallback


def _parse_json_like(output: object) -> Any | None:
    if isinstance(output, BaseModel):
        try:
            output = output.model_dump()
        except Exception:
            output = str(output)
    if isinstance(output, (dict, list)):
        return output
    if not isinstance(output, str):
        return None
    text = output.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _stringify(output: object) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False)
    except TypeError:
        return str(output)


def _dump(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _fit_candidates(
    builders: list[Callable[[], dict[str, Any]]],
    max_chars: int,
) -> str | None:
    last_text: str | None = None
    for build in builders:
        candidate = build()
        text = _dump(candidate)
        last_text = text
        if len(text) <= max_chars:
            return text
    if last_text is None:
        return None
    return "{}" if max_chars >= 2 else "0"


def _truncate_text(value: object, limit: int) -> str:
    text = str(value or "")
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(_ELLIPSIS):
        return _ELLIPSIS[:limit]
    return f"{text[: limit - len(_ELLIPSIS)].rstrip()}{_ELLIPSIS}"


def _truncate_json_content(
    base_payload: dict[str, Any],
    *,
    content: str,
    max_chars: int,
) -> str:
    best: str | None = None
    low = 0
    high = len(content)
    while low <= high:
        mid = (low + high) // 2
        candidate = dict(base_payload)
        candidate["content"] = _truncate_text(content, mid)
        text = _dump(candidate)
        if len(text) <= max_chars:
            best = text
            low = mid + 1
        else:
            high = mid - 1
    if best is not None:
        return best
    empty_candidate = dict(base_payload)
    empty_candidate["content"] = ""
    empty_text = _dump(empty_candidate)
    if len(empty_text) <= max_chars:
        return empty_text
    return "{}" if max_chars >= 2 else "0"


def _compact_error(error: object, *, detail_limit: int) -> dict[str, Any] | None:
    if error is None:
        return None
    if not isinstance(error, dict):
        return {"message": _truncate_text(error, detail_limit)}
    return {
        "code": error.get("code"),
        "message": _truncate_text(error.get("message"), 160),
        "retryable": error.get("retryable"),
        "status_code": error.get("status_code"),
        "detail": _truncate_text(error.get("detail"), detail_limit),
    }


def _clean_item(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in payload.items() if value not in (None, "", [], {})
    }


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _compact_search_result(item: object, *, snippet_limit: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    snippet_source = (
        item.get("snippet") or item.get("content") or item.get("raw_content")
    )
    return _clean_item(
        {
            "title": _truncate_text(item.get("title"), 120),
            "url": _truncate_text(item.get("url"), 240),
            "snippet": _truncate_text(snippet_source, snippet_limit),
            "source": item.get("source"),
            "domain": _truncate_text(item.get("domain"), 80),
            "published_at": _truncate_text(item.get("published_at"), 40),
        }
    )


def _compact_extract_result(
    item: object,
    *,
    snippet_limit: int,
    raw_content_limit: int,
    include_raw_content: bool = True,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    raw_content = (
        _truncate_text(
            item.get("raw_content") or item.get("content"), raw_content_limit
        )
        if include_raw_content
        else ""
    )
    return _clean_item(
        {
            "title": _truncate_text(item.get("title"), 120),
            "url": _truncate_text(item.get("url"), 240),
            "snippet": _truncate_text(item.get("snippet"), snippet_limit),
            "raw_content": raw_content,
            "source": item.get("source"),
        }
    )


def _compact_provider_report(item: object, *, detail_limit: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return _clean_item(
        {
            "provider": item.get("provider"),
            "ok": item.get("ok"),
            "result_count": item.get("result_count"),
            "elapsed_ms": item.get("elapsed_ms"),
            "error": _compact_error(item.get("error"), detail_limit=detail_limit),
        }
    )


def _compact_query_plan(
    payload: Any, *, query_limit: int, rewritten_limit: int
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    rewritten_queries = payload.get("rewritten_queries")
    compacted_queries = (
        [
            _truncate_text(item, rewritten_limit)
            for item in rewritten_queries[:3]
            if isinstance(item, str) and item.strip()
        ]
        if isinstance(rewritten_queries, list)
        else []
    )
    compacted = _clean_item(
        {
            "original_query": _truncate_text(
                payload.get("original_query"), query_limit
            ),
            "rewritten_queries": compacted_queries,
        }
    )
    return compacted or None


def _compact_web_search_output(payload: Any, max_chars: int) -> str | None:
    if not isinstance(payload, dict):
        return None

    raw_results = payload.get("results")
    raw_reports = payload.get("provider_reports")
    results = raw_results if isinstance(raw_results, list) else []
    provider_reports = raw_reports if isinstance(raw_reports, list) else []

    builders = [
        lambda: {
            "query": _truncate_text(payload.get("query"), 200),
            "query_plan": _compact_query_plan(
                payload.get("query_plan"), query_limit=160, rewritten_limit=160
            ),
            "results": [
                _compact_search_result(item, snippet_limit=260)
                for item in results[:5]
                if isinstance(item, dict)
            ],
            "provider_reports": [
                _compact_provider_report(item, detail_limit=160)
                for item in provider_reports[:4]
                if isinstance(item, dict)
            ],
            "merged_count": _safe_int(
                payload.get("merged_count"), default=len(results)
            ),
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=160),
        },
        lambda: {
            "query": _truncate_text(payload.get("query"), 120),
            "query_plan": _compact_query_plan(
                payload.get("query_plan"), query_limit=100, rewritten_limit=100
            ),
            "results": [
                _compact_search_result(item, snippet_limit=120)
                for item in results[:2]
                if isinstance(item, dict)
            ],
            "provider_reports": [
                _compact_provider_report(item, detail_limit=100)
                for item in provider_reports[:2]
                if isinstance(item, dict)
            ],
            "merged_count": _safe_int(
                payload.get("merged_count"), default=len(results)
            ),
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=100),
        },
        lambda: {
            "query": _truncate_text(payload.get("query"), 80),
            "query_plan": _compact_query_plan(
                payload.get("query_plan"), query_limit=72, rewritten_limit=72
            ),
            "results": [
                _compact_search_result(item, snippet_limit=72)
                for item in results[:1]
                if isinstance(item, dict)
            ],
            "provider_reports": [
                _compact_provider_report(item, detail_limit=72)
                for item in provider_reports[:1]
                if isinstance(item, dict)
            ],
            "merged_count": _safe_int(
                payload.get("merged_count"), default=len(results)
            ),
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=72),
        },
        lambda: {
            "query": _truncate_text(payload.get("query"), 60),
            "query_plan": _compact_query_plan(
                payload.get("query_plan"), query_limit=56, rewritten_limit=56
            ),
            "results": [],
            "provider_reports": [],
            "merged_count": _safe_int(
                payload.get("merged_count"), default=len(results)
            ),
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=60),
        },
    ]
    return _fit_candidates(builders, max_chars)


def _compact_web_extract_output(payload: Any, max_chars: int) -> str | None:
    if not isinstance(payload, dict):
        return None

    raw_results = payload.get("results")
    results = raw_results if isinstance(raw_results, list) else []

    builders = [
        lambda: {
            "results": [
                _compact_extract_result(
                    item,
                    snippet_limit=120,
                    raw_content_limit=240,
                )
                for item in results[:2]
                if isinstance(item, dict)
            ],
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=140),
        },
        lambda: {
            "results": [
                _compact_extract_result(
                    item,
                    snippet_limit=80,
                    raw_content_limit=120,
                )
                for item in results[:1]
                if isinstance(item, dict)
            ],
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=90),
        },
        lambda: {
            "results": [
                _compact_extract_result(
                    item,
                    snippet_limit=40,
                    raw_content_limit=0,
                    include_raw_content=False,
                )
                for item in results[:1]
                if isinstance(item, dict)
            ],
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=60),
        },
        lambda: {
            "results": [],
            "elapsed_ms": _safe_int(payload.get("elapsed_ms")),
            "error": _compact_error(payload.get("error"), detail_limit=60),
        },
    ]
    return _fit_candidates(builders, max_chars)


def _compact_jina_read_output(payload: Any, max_chars: int) -> str | None:
    if not isinstance(payload, dict):
        return None

    base_payload = {
        "url": _truncate_text(payload.get("url"), 240),
        "title": _truncate_text(payload.get("title"), 120),
        "error": _compact_error(payload.get("error"), detail_limit=120),
    }
    content = str(payload.get("content") or "")

    primary = _truncate_json_content(
        base_payload,
        content=content,
        max_chars=max_chars,
    )
    if len(primary) <= max_chars:
        return primary

    fallback_base = {
        "url": _truncate_text(payload.get("url"), 120),
        "title": _truncate_text(payload.get("title"), 60),
        "error": _compact_error(payload.get("error"), detail_limit=72),
    }
    return _truncate_json_content(
        fallback_base,
        content=content,
        max_chars=max_chars,
    )
