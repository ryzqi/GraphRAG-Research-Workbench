"""SearchDocument 与 LangChain Document 互转工具。"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langchain_core.documents import Document

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
}


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
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key
        and not key.lower().startswith("utm_")
        and key.lower() not in _TRACKING_QUERY_KEYS
    ]
    normalized_query = urlencode(filtered_query, doseq=True)
    return urlunsplit((scheme, netloc, path, normalized_query, ""))


def extract_domain(url: str) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except Exception:
        return None
    return host.lower() if isinstance(host, str) and host else None


def build_document(
    *,
    provider: str,
    provider_rank: int,
    query: str,
    title: str,
    url: str,
    snippet: str,
    published_at: str | None = None,
    raw_score: float | None = None,
) -> Document:
    canonical_url = canonicalize_url(url)
    resolved_url = canonical_url or url.strip()
    return Document(
        page_content=str(snippet or "").strip(),
        metadata={
            "provider": provider,
            "provider_rank": provider_rank,
            "retrieval_query": query,
            "title": str(title or "").strip(),
            "url": resolved_url,
            "canonical_url": resolved_url,
            "domain": extract_domain(resolved_url),
            "published_at": str(published_at).strip() if published_at else None,
            "raw_score": raw_score,
            "fusion_score": 0.0,
            "overlap_count": 1,
            "enriched": False,
        },
    )


def merge_document_metadata(base: Document, **updates: Any) -> Document:
    metadata = dict(base.metadata)
    metadata.update({key: value for key, value in updates.items() if value is not None})
    return Document(page_content=base.page_content, metadata=metadata)


def _resolve_snippet_locator(metadata: dict[str, Any]) -> str:
    hint = (
        str(metadata.get("section") or "").strip()
        or str(metadata.get("anchor") or "").strip()
        or str(metadata.get("title") or "").strip()
        or "snippet"
    )
    return hint[:80] or "snippet"


def document_to_result(document: Document) -> dict[str, Any]:
    metadata = dict(document.metadata)
    return {
        "title": str(metadata.get("title") or "").strip(),
        "url": str(metadata.get("url") or "").strip(),
        "snippet": str(document.page_content or "").strip(),
        "snippet_locator": _resolve_snippet_locator(metadata),
        "source": str(metadata.get("provider") or "").strip(),
        "domain": str(metadata.get("domain") or "").strip()
        or extract_domain(str(metadata.get("url") or "")),
        "published_at": str(metadata.get("published_at") or "").strip() or None,
        "provider_rank": metadata.get("provider_rank"),
        "retrieval_query": str(metadata.get("retrieval_query") or "").strip(),
        "overlap_count": int(metadata.get("overlap_count") or 1),
        "fusion_score": float(metadata.get("fusion_score") or 0.0),
        "enriched": bool(metadata.get("enriched")),
    }


def document_title(document: Document) -> str:
    return str(document.metadata.get("title") or "").strip()


def document_url(document: Document) -> str:
    return str(document.metadata.get("url") or "").strip()
