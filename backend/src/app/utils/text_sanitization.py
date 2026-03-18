from __future__ import annotations

import unicodedata


def sanitize_visible_text(text: str) -> str:
    """Remove invisible Unicode format characters and trim outer whitespace."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf").strip()


def has_visible_text(text: str) -> bool:
    return bool(sanitize_visible_text(text))
