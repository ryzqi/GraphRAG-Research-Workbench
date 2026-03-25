from __future__ import annotations

import unicodedata


def sanitize_visible_text(text: str) -> str:
    """移除不可见 Unicode 格式字符，并裁剪首尾空白。"""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf").strip()


def has_visible_text(text: str) -> bool:
    return bool(sanitize_visible_text(text))
