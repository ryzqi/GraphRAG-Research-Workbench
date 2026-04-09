"""用于规范引用处理的结构化 KB 证据辅助函数。"""

from __future__ import annotations

from typing import Any

from app.services.evidence_guardrails import (
    extract_citation_labels,
    is_stable_citation_id,
    normalize_citation_label,
)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def normalize_stable_citation_id(value: object) -> str | None:
    raw = _as_text(value).strip()
    if not raw:
        return None
    normalized = normalize_citation_label(raw).upper()
    if not is_stable_citation_id(normalized):
        return None
    return normalized


def stable_citation_sort_key(citation_id: str) -> tuple[int, str]:
    normalized = (
        normalize_stable_citation_id(citation_id)
        or _as_text(citation_id).strip().upper()
    )
    digits = normalized[1:] if normalized.startswith("S") else ""
    if digits.isdigit():
        return int(digits), normalized
    return 10_000_000, normalized


def extract_stable_citation_ids(text: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for label in extract_citation_labels(text or ""):
        normalized = normalize_stable_citation_id(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def normalize_citation_catalog(citation_catalog: object) -> dict[str, dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(citation_catalog, dict):
        items = [
            value
            for key, value in citation_catalog.items()
            if isinstance(value, dict) or isinstance(key, str)
        ]
    elif isinstance(citation_catalog, list):
        items = [value for value in citation_catalog if isinstance(value, dict)]

    normalized: dict[str, dict[str, Any]] = {}
    for raw in items:
        citation_id = normalize_stable_citation_id(
            raw.get("citation_id") or raw.get("id") or raw.get("label")
        )
        if citation_id is None:
            continue
        entry = dict(raw)
        entry["citation_id"] = citation_id
        if not entry.get("citation_title") and isinstance(entry.get("title"), str):
            entry["citation_title"] = entry.get("title")
        if not entry.get("citation_source") and isinstance(entry.get("source"), str):
            entry["citation_source"] = entry.get("source")
        normalized[citation_id] = entry
    return normalized


def _evidence_identity_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    chunk_id = _as_text(item.get("chunk_id")).strip()
    material_id = _as_text(item.get("material_id")).strip()
    kb_id = _as_text(item.get("kb_id")).strip()
    excerpt = _as_text(item.get("excerpt")).strip().casefold()
    return chunk_id, material_id, kb_id, excerpt


def _merge_catalog_fields(
    item: dict[str, Any],
    *,
    catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    citation_id = item.get("citation_id")
    if not isinstance(citation_id, str):
        return item
    meta = catalog.get(citation_id)
    if not isinstance(meta, dict):
        return item
    merged = dict(item)
    for key in (
        "citation_title",
        "citation_source",
        "citation_page_hint",
        "source_excerpt",
        "material_title",
        "locator",
        "chunk_id",
        "material_id",
        "kb_id",
    ):
        value = merged.get(key)
        if value not in (None, "", []):
            continue
        meta_value = meta.get(key)
        if meta_value in (None, "", []):
            continue
        merged[key] = meta_value
    return merged


def canonicalize_evidence_items(
    evidence_items: object,
    *,
    citation_catalog: object = None,
    reindex: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    catalog = normalize_citation_catalog(citation_catalog)
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    if not isinstance(evidence_items, list):
        return [], {}

    for index, raw in enumerate(evidence_items, 1):
        if not isinstance(raw, dict):
            continue
        citation_id = (
            normalize_stable_citation_id(raw.get("citation_id")) or f"S{index}"
        )
        excerpt = _as_text(raw.get("excerpt")).strip()
        if not excerpt:
            continue
        item = dict(raw)
        item["citation_id"] = citation_id
        item["excerpt"] = excerpt
        item = _merge_catalog_fields(item, catalog=catalog)
        identity = _evidence_identity_key(item)
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(item)

    if reindex:
        remapped: list[dict[str, Any]] = []
        for index, item in enumerate(normalized, 1):
            remapped.append({**item, "citation_id": f"S{index}"})
        normalized = remapped

    return normalized, build_citation_catalog(normalized)


def resolve_structured_evidence(
    evidence_items: object,
    *,
    citation_catalog: object = None,
    reindex: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    normalized_items, normalized_catalog = canonicalize_evidence_items(
        evidence_items,
        citation_catalog=citation_catalog,
        reindex=reindex,
    )
    return (
        normalized_items,
        normalized_catalog,
        build_evidence_context(normalized_items),
    )


def build_citation_catalog(
    evidence_items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for item in evidence_items:
        citation_id = normalize_stable_citation_id(item.get("citation_id"))
        if citation_id is None:
            continue
        catalog[citation_id] = {
            "citation_id": citation_id,
            "material_title": item.get("material_title"),
            "citation_title": item.get("citation_title"),
            "citation_source": item.get("citation_source"),
            "citation_page_hint": item.get("citation_page_hint"),
            "source_excerpt": item.get("source_excerpt"),
            "locator": item.get("locator"),
            "chunk_id": item.get("chunk_id"),
            "material_id": item.get("material_id"),
            "kb_id": item.get("kb_id"),
        }
    return catalog


def select_evidence_items_by_citation_ids(
    evidence_items: object,
    citation_ids: list[str] | tuple[str, ...] | set[str],
) -> list[dict[str, Any]]:
    if not isinstance(evidence_items, list):
        return []
    by_id: dict[str, dict[str, Any]] = {}
    for raw in evidence_items:
        if not isinstance(raw, dict):
            continue
        citation_id = normalize_stable_citation_id(raw.get("citation_id"))
        if citation_id is None or citation_id in by_id:
            continue
        by_id[citation_id] = raw

    selected: list[dict[str, Any]] = []
    for raw_id in citation_ids:
        citation_id = normalize_stable_citation_id(raw_id)
        if citation_id is None or citation_id not in by_id:
            continue
        selected.append(dict(by_id[citation_id]))
    return selected


def build_evidence_context(evidence_items: object) -> str:
    if not isinstance(evidence_items, list):
        return "（未找到相关内容）"
    parts: list[str] = []
    for raw in evidence_items:
        if not isinstance(raw, dict):
            continue
        citation_id = normalize_stable_citation_id(raw.get("citation_id"))
        excerpt = _as_text(raw.get("excerpt")).strip()
        if citation_id is None or not excerpt:
            continue
        parts.append(f"[{citation_id}] {excerpt}")
    return "\n\n".join(parts) if parts else "（未找到相关内容）"
