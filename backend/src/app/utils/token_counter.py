"""Token counting and token-window helpers."""

from __future__ import annotations

from functools import lru_cache
try:  # pragma: no cover
    import tiktoken
except Exception:  # pragma: no cover
    tiktoken = None  # type: ignore[assignment]

_APPROX_TOKEN_CHARS = 4
_DEFAULT_ENCODING = "cl100k_base"


def count_tokens_approximately(text: str) -> int:
    """Estimate token count with a stable heuristic (chars/4, ceil)."""
    if not text:
        return 0
    return max((len(text) + (_APPROX_TOKEN_CHARS - 1)) // _APPROX_TOKEN_CHARS, 1)


@lru_cache(maxsize=16)
def _get_encoding(model: str | None):
    if tiktoken is None:
        return None

    normalized = (model or "").strip()
    if normalized:
        try:
            return tiktoken.encoding_for_model(normalized)
        except Exception:
            pass

    try:
        return tiktoken.get_encoding(_DEFAULT_ENCODING)
    except Exception:
        return None


def count_tokens(text: str, *, model: str | None = None) -> int:
    """Count tokens via tiktoken when available, otherwise fallback to approximation."""
    if not text:
        return 0

    encoding = _get_encoding(model)
    if encoding is None:
        return count_tokens_approximately(text)

    try:
        return max(len(encoding.encode(text)), 1)
    except Exception:
        return count_tokens_approximately(text)


def split_text_by_token_windows(
    text: str,
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int = 0,
    model: str | None = None,
) -> list[dict[str, int | str]]:
    """Split text by token windows, preserving token start/end metadata."""
    if not text:
        return []

    chunk_size_tokens = max(int(chunk_size_tokens), 1)
    chunk_overlap_tokens = max(int(chunk_overlap_tokens), 0)
    step_tokens = max(chunk_size_tokens - chunk_overlap_tokens, 1)

    encoding = _get_encoding(model)
    if encoding is not None:
        try:
            token_ids = encoding.encode(text)
        except Exception:
            token_ids = []

        if token_ids:
            total_tokens = len(token_ids)
            chunks: list[dict[str, int | str]] = []
            token_start = 0
            while token_start < total_tokens:
                token_end = min(token_start + chunk_size_tokens, total_tokens)
                chunk_text = encoding.decode(token_ids[token_start:token_end]).strip()
                if chunk_text:
                    chunks.append(
                        {
                            "text": chunk_text,
                            "token_start": token_start,
                            "token_end": token_end,
                        }
                    )
                if token_end >= total_tokens:
                    break
                token_start += step_tokens
            return chunks

    total_tokens = max(count_tokens_approximately(text), 1)
    chunks = []
    token_start = 0
    while token_start < total_tokens:
        token_end = min(token_start + chunk_size_tokens, total_tokens)
        char_start = token_start * _APPROX_TOKEN_CHARS
        char_end = min(len(text), token_end * _APPROX_TOKEN_CHARS)
        chunk_text = text[char_start:char_end].strip()
        if chunk_text:
            chunks.append(
                {
                    "text": chunk_text,
                    "token_start": token_start,
                    "token_end": token_end,
                }
            )
        if token_end >= total_tokens:
            break
        token_start += step_tokens
    return chunks


def split_text_to_token_budget(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int = 0,
    model: str | None = None,
) -> list[str]:
    """Split text into chunks whose token spans fit the provided budget."""
    windows = split_text_by_token_windows(
        text,
        chunk_size_tokens=max(max_tokens, 1),
        chunk_overlap_tokens=max(overlap_tokens, 0),
        model=model,
    )
    return [str(item["text"]) for item in windows if str(item.get("text", "")).strip()]
