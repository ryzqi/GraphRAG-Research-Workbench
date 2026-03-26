"""网页搜索 provider 共享契约。"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

SearchProviderName = Literal["tavily", "jina_reader", "searxng"]


class NormalizedSearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source_provider: SearchProviderName
    score: float | None = None
    published_at: str | None = None
    domain: str | None = None


class ProviderSearchReport(BaseModel):
    provider: SearchProviderName
    ok: bool
    result_count: int
    elapsed_ms: int
    error: dict[str, Any] | None = None


class ProviderSearchResponse(BaseModel):
    provider: SearchProviderName
    results: list[NormalizedSearchResult] = Field(default_factory=list)
    report: ProviderSearchReport


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except Exception:
        return raw
    scheme = (parts.scheme or "https").lower()
    netloc = (parts.netloc or "").lower()
    path = parts.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def extract_domain(url: str) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except Exception:
        return None
    return host.lower() if isinstance(host, str) and host else None


def build_provider_error(
    *,
    code: str,
    message: str,
    retryable: bool = False,
    detail: str | None = None,
    status_code: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if status_code is not None:
        payload["status_code"] = status_code
    if detail:
        payload["detail"] = detail[:300]
    return payload
