"""研究工具 excerpt 片段辅助。"""

from __future__ import annotations


def build_excerpt_candidates_from_text(
    text: str,
    *,
    locator_prefix: str = "abstract",
) -> list[dict[str, str]]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    chunks: list[str] = []
    remaining = normalized
    while remaining and len(chunks) < 3:
        head = remaining[:380].strip()
        if len(head) < 40:
            break
        chunks.append(head)
        remaining = remaining[len(head) :].strip()
    if not chunks and len(normalized) >= 40:
        chunks.append(normalized[:400])
    return [
        {
            "text": chunk,
            "locator": f"{locator_prefix}#chunk-{index + 1}",
            "lang": "en",
        }
        for index, chunk in enumerate(chunks)
    ]
