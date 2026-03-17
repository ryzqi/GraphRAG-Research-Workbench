from __future__ import annotations

_INVISIBLE_TEXT_CHARS = "\u200b\u200c\u200d\u2060\ufeff"
_INVISIBLE_TEXT_TRANSLATION = str.maketrans("", "", _INVISIBLE_TEXT_CHARS)


def sanitize_visible_text(text: str) -> str:
    """Remove a tiny set of invisible characters and trim outer whitespace."""
    return text.translate(_INVISIBLE_TEXT_TRANSLATION).strip()


def has_visible_text(text: str) -> bool:
    return bool(sanitize_visible_text(text))
