from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.semantic_cache.models import SemanticCacheContext, SemanticCacheScope
from app.utils.text_sanitization import sanitize_visible_text

SEMANTIC_CACHE_SCHEMA_VERSION = "v4"
SEMANTIC_CACHE_ANSWER_CONTRACT_VERSION = "kb_chat_semantic_cache_v4"
SEMANTIC_CACHE_VERIFIED_LEVEL_DIRECT = "verified_direct"
SEMANTIC_CACHE_HIT_TYPE_STRONG = "strong_hit"

_CONTEXTUAL_MARKERS = (
    "它",
    "它们",
    "他",
    "他们",
    "她",
    "她们",
    "前者",
    "后者",
    "这个",
    "那个",
    "这些",
    "那些",
    "上面",
    "前面",
    "刚才",
    "继续",
    "分别",
)


def build_scope(
    *,
    kb_ids: list[str],
    allow_external: bool,
    mode: str,
    config_fingerprint: str,
    kb_version: str,
) -> SemanticCacheScope:
    scope_payload = {
        "kb_ids": sorted(kb_ids),
        "allow_external": bool(allow_external),
        "mode": str(mode or ""),
        "config_fingerprint": str(config_fingerprint or ""),
        "kb_version": str(kb_version or ""),
    }
    raw = json.dumps(scope_payload, ensure_ascii=False, sort_keys=True)
    return SemanticCacheScope(
        scope_fingerprint=hashlib.sha1(raw.encode("utf-8")).hexdigest(),
        kb_version=str(kb_version or ""),
        mode=str(mode or ""),
        allow_external=bool(allow_external),
        config_fingerprint=str(config_fingerprint or ""),
    )


def build_context(*, question: str, pre_context: dict[str, Any]) -> SemanticCacheContext:
    if is_contextual_query(question):
        return SemanticCacheContext(
            mode="contextual",
            signature=build_context_signature(pre_context),
        )
    return SemanticCacheContext(mode="standalone", signature=None)


def is_contextual_query(question: str) -> bool:
    normalized = sanitize_visible_text(str(question or "")).strip()
    if not normalized:
        return False
    return any(marker in normalized for marker in _CONTEXTUAL_MARKERS)


def build_context_signature(pre_context: dict[str, Any]) -> str:
    summary_text = sanitize_visible_text(str(pre_context.get("summary_text") or "")) or ""
    recent_turns_raw = pre_context.get("recent_turns")
    recent_turns: list[dict[str, str]] = []
    if isinstance(recent_turns_raw, list):
        for item in recent_turns_raw:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = sanitize_visible_text(str(item.get("content") or "")) or ""
            if role not in {"user", "assistant"} or not content:
                continue
            recent_turns.append({"role": role, "content": content})
    raw = json.dumps(
        {
            "summary_text": summary_text,
            "recent_turns": recent_turns,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def similarity_threshold_to_distance(threshold: float) -> float:
    normalized = max(0.0, min(1.0, float(threshold)))
    return max(0.0, min(1.0, 1.0 - normalized))


def distance_to_similarity_score(distance: float) -> float:
    return max(0.0, min(1.0, 1.0 - float(distance)))
