"""普通聊天外部来源的紧凑引用。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain.messages import ToolMessage

from app.models.evidence import EvidenceSourceKind
from app.schemas.chats import EvidenceItem

from .documents import canonicalize_url, extract_domain

_EXCERPT_LIMIT = 500
_SOURCE_EXCERPT_LIMIT = 1200
_REFERENCE_HEADING = "参考来源"
_REFERENCE_LINE_RE = re.compile(r"^\[(\d+)\]\s+([^\s]+)\s+-\s+(.+)$")
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
}


def _trim_text(value: object, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part.strip())
    return ""


def _load_payload(content: object) -> dict[str, Any] | None:
    text = _content_to_text(content)
    if not text.strip():
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _compact_locator(
    *,
    url: str,
    title: str | None = None,
    provider: str | None = None,
    domain: str | None = None,
    published_at: str | None = None,
) -> dict[str, Any]:
    locator: dict[str, Any] = {"source": url, "url": url}
    if title:
        locator["material_title"] = title
    if provider:
        locator["provider"] = provider
    locator_domain = domain or extract_domain(url)
    if locator_domain:
        locator["domain"] = locator_domain
    if published_at:
        locator["published_at"] = published_at
    return locator


def _normalize_evidence_url(url: str) -> str:
    canonical = canonicalize_url(url)
    if not canonical:
        return ""
    match = re.match(r"^(https?://[^?#]+)(?:\?([^#]*))?$", canonical)
    if not match:
        return canonical
    base = match.group(1)
    query = match.group(2) or ""
    if not query:
        return base
    pairs = []
    for chunk in query.split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_QUERY_KEYS:
            continue
        pairs.append(chunk if value else key)
    if not pairs:
        return base
    return f"{base}?{'&'.join(pairs)}"


def _merge_locator(
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(current) if isinstance(current, dict) else {}
    for key, value in incoming.items():
        if value in (None, "", []):
            continue
        merged[key] = value
    return merged


def _build_evidence_item(
    *,
    url: str,
    locator: dict[str, Any],
    excerpt: str,
    source_excerpt: str | None = None,
    citation_title: str | None = None,
) -> EvidenceItem:
    resolved_title = (
        citation_title
        or (locator.get("material_title") if isinstance(locator, dict) else None)
        or "外部来源"
    )
    return EvidenceItem(
        source_kind=EvidenceSourceKind.EXTERNAL,
        locator=locator,
        excerpt=excerpt,
        source_excerpt=source_excerpt,
        citation_title=resolved_title,
        citation_source=url,
    )


def _upsert_search_result(
    items_by_url: dict[str, EvidenceItem],
    item: dict[str, Any],
) -> None:
    url = _normalize_evidence_url(str(item.get("url") or "").strip())
    if not url:
        return
    existing = items_by_url.get(url)
    title = str(item.get("title") or "").strip() or None
    locator = _merge_locator(
        existing.locator if existing else None,
        _compact_locator(
            url=url,
            title=title,
            provider=str(item.get("source") or "").strip() or None,
            domain=str(item.get("domain") or "").strip() or None,
            published_at=str(item.get("published_at") or "").strip() or None,
        ),
    )
    excerpt = (
        existing.excerpt
        if existing and existing.excerpt.strip()
        else _trim_text(
            item.get("snippet") or item.get("content"), limit=_EXCERPT_LIMIT
        )
    )
    items_by_url[url] = _build_evidence_item(
        url=url,
        locator=locator,
        excerpt=excerpt,
        source_excerpt=existing.source_excerpt if existing else None,
        citation_title=title or (existing.citation_title if existing else None),
    )


def _upsert_content_result(
    items_by_url: dict[str, EvidenceItem],
    *,
    url: str,
    title: str | None,
    provider: str | None = None,
    domain: str | None = None,
    published_at: str | None = None,
    content: object,
) -> None:
    normalized_url = _normalize_evidence_url(str(url or "").strip())
    normalized_content = _trim_text(content, limit=_SOURCE_EXCERPT_LIMIT)
    if not normalized_url or not normalized_content:
        return
    existing = items_by_url.get(normalized_url)
    locator = _merge_locator(
        existing.locator if existing else None,
        _compact_locator(
            url=normalized_url,
            title=(str(title).strip() if title else None) or None,
            provider=provider,
            domain=domain,
            published_at=published_at,
        ),
    )
    items_by_url[normalized_url] = _build_evidence_item(
        url=normalized_url,
        locator=locator,
        excerpt=_trim_text(normalized_content, limit=_EXCERPT_LIMIT),
        source_excerpt=normalized_content,
        citation_title=(str(title).strip() if title else None)
        or (existing.citation_title if existing else None),
    )


def extract_external_evidence_from_messages(
    messages: Sequence[object],
) -> list[EvidenceItem]:
    """从普通代理 ToolMessage 中抽取 external evidence。"""

    items_by_url: dict[str, EvidenceItem] = {}
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        payload = _load_payload(message.content)
        if payload is None or payload.get("error"):
            continue
        if message.name == "web_search":
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                continue
            for item in raw_results:
                if isinstance(item, dict):
                    _upsert_search_result(items_by_url, item)
            continue
        if message.name == "web_extract":
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                continue
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                _upsert_content_result(
                    items_by_url,
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or "").strip() or None,
                    provider=str(item.get("source") or "").strip() or None,
                    domain=str(item.get("domain") or "").strip() or None,
                    published_at=str(item.get("published_at") or "").strip() or None,
                    content=item.get("raw_content")
                    or item.get("content")
                    or item.get("snippet"),
                )
            continue
        if message.name == "jina_read":
            _upsert_content_result(
                items_by_url,
                url=str(payload.get("url") or ""),
                title=str(payload.get("title") or "").strip() or None,
                content=payload.get("content"),
            )
    return list(items_by_url.values())


def _resolve_reference_url(item: EvidenceItem) -> str | None:
    candidates: list[str] = []
    if isinstance(item.citation_source, str):
        candidates.append(item.citation_source)
    if isinstance(item.locator, dict):
        for key in ("url", "source"):
            value = item.locator.get(key)
            if isinstance(value, str):
                candidates.append(value)
    for candidate in candidates:
        normalized = canonicalize_url(candidate.strip())
        if normalized.startswith(("http://", "https://")):
            return normalized
    return None


def _resolve_reference_title(item: EvidenceItem) -> str:
    if isinstance(item.citation_title, str) and item.citation_title.strip():
        return item.citation_title.strip()
    if isinstance(item.locator, dict):
        title = item.locator.get("material_title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return "外部来源"


def _build_compact_entries(items: Sequence[EvidenceItem]) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()
    for item in items:
        url = _resolve_reference_url(item)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        domain = extract_domain(url) or url
        entries.append((domain, _resolve_reference_title(item), url))
    return entries


def _split_reference_block(answer: str) -> tuple[str, list[tuple[str, str]]]:
    normalized = str(answer or "").replace("\r\n", "\n").rstrip()
    if not normalized:
        return "", []
    marker = f"\n{_REFERENCE_HEADING}\n"
    inline_marker = f"{_REFERENCE_HEADING}\n"
    split_token = (
        marker
        if marker in normalized
        else inline_marker
        if normalized.startswith(inline_marker)
        else None
    )
    if split_token is None:
        return normalized, []

    if split_token == inline_marker and normalized.startswith(inline_marker):
        body = normalized[len(inline_marker) :]
        prefix = ""
    else:
        prefix, body = normalized.split(marker, 1)
    existing: list[tuple[str, str]] = []
    for line in body.splitlines():
        match = _REFERENCE_LINE_RE.match(line.strip())
        if not match:
            continue
        existing.append((match.group(2).strip(), match.group(3).strip()))
    return prefix.rstrip(), existing


def append_compact_citations_to_answer(
    answer: str, items: Sequence[EvidenceItem]
) -> str:
    compact_entries = _build_compact_entries(items)
    prefix, existing_entries = _split_reference_block(answer)
    merged_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for domain, title in existing_entries:
        pair = (domain, title)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        merged_pairs.append(pair)

    for domain, title, _ in compact_entries:
        pair = (domain, title)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        merged_pairs.append(pair)

    if not merged_pairs:
        return prefix

    block = "\n".join(
        [
            _REFERENCE_HEADING,
            *[
                f"[{index}] {domain} - {title}"
                for index, (domain, title) in enumerate(merged_pairs, start=1)
            ],
        ]
    )
    if prefix:
        return f"{prefix}\n\n{block}"
    return block
