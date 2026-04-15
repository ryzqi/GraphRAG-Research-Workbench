from __future__ import annotations

import math
import re

from app.schemas.knowledge_bases import IndexConfig, SemanticThresholdMode
from app.services.parsing.types import ParsedChunk
from app.utils.token_counter import (
    count_tokens,
    split_text_by_token_windows,
    split_text_to_token_budget,
)

_SENTENCE_DELIMS = set("。！？!?;；:")
_APPROX_TOKEN_CHARS = 4
_ENGLISH_ABBREVIATIONS = {
    "e.g",
    "i.e",
    "etc",
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "vs",
    "u.s",
    "u.k",
}


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    buf: list[str] = []

    def _flush() -> None:
        sentence = "".join(buf).strip()
        if sentence:
            sentences.append(sentence)
        buf.clear()

    for idx, ch in enumerate(text):
        buf.append(ch)
        if ch == "\n":
            _flush()
            continue

        if ch in _SENTENCE_DELIMS and ch != ".":
            _flush()
            continue

        if ch == "." and _should_split_on_period(buf, source=text, period_index=idx):
            _flush()

    if buf:
        _flush()
    return sentences


def _should_split_on_period(
    buf: list[str],
    *,
    source: str,
    period_index: int,
) -> bool:
    if not buf:
        return False
    text = "".join(buf).rstrip()
    if not text.endswith("."):
        return False

    token = _tail_alpha_token(text[:-1])
    if token and token.lower() in _ENGLISH_ABBREVIATIONS:
        return False

    if len(text) >= 4 and re.search(r"(?:[A-Za-z]\.){2,}$", text):
        return False

    prev_char = text[-2] if len(text) >= 2 else ""
    next_char = _next_non_space_char(source, period_index + 1)
    if (
        len(token) == 1
        and prev_char.isalpha()
        and isinstance(next_char, str)
        and next_char.isalpha()
    ):
        return False

    if prev_char.isdigit() and isinstance(next_char, str) and next_char.isdigit():
        return False

    return True


def _tail_alpha_token(text: str) -> str:
    i = len(text) - 1
    while i >= 0 and text[i].isspace():
        i -= 1
    end = i + 1
    while i >= 0 and text[i].isalpha():
        i -= 1
    return text[i + 1 : end]


def _next_non_space_char(text: str, start_index: int) -> str | None:
    idx = max(start_index, 0)
    while idx < len(text):
        ch = text[idx]
        if not ch.isspace():
            return ch
        idx += 1
    return None


def _first_query_dependent_multiscale_window(
    index_config: IndexConfig,
) -> tuple[int, int]:
    windows = index_config.chunking.query_dependent_multiscale.windows
    if windows:
        window = windows[0]
        return window.chunk_size_tokens, window.chunk_overlap_tokens

    semantic_cfg = index_config.chunking.semantic
    chunk_size_tokens = max(int(semantic_cfg.max_tokens), 1)
    overlap_tokens = max(int(semantic_cfg.overlap_chars // _APPROX_TOKEN_CHARS), 0)
    overlap_tokens = min(overlap_tokens, max(chunk_size_tokens - 1, 0))
    return chunk_size_tokens, overlap_tokens


def _first_query_dependent_multiscale_window_chars(
    index_config: IndexConfig,
) -> tuple[int, int]:
    chunk_size_tokens, chunk_overlap_tokens = _first_query_dependent_multiscale_window(
        index_config
    )
    return (
        chunk_size_tokens * _APPROX_TOKEN_CHARS,
        chunk_overlap_tokens * _APPROX_TOKEN_CHARS,
    )


def _split_sliding_window(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - chunk_overlap if end < len(text) else end
    return chunks


def _split_sliding_window_by_tokens(
    text: str,
    *,
    chunk_size_tokens: int,
    chunk_overlap_tokens: int,
    model: str | None = None,
) -> list[dict[str, int | str]]:
    if not text:
        return []

    return split_text_by_token_windows(
        text,
        chunk_size_tokens=chunk_size_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        model=model,
    )


def _merge_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left.endswith(("\n", " ", "\t")) or right.startswith(("\n", " ", "\t")):
        return f"{left}{right}"
    return f"{left}\n{right}"


def _apply_overlap(previous: str, next_text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or not previous:
        return next_text
    tail = previous[-overlap_chars:]
    return _merge_text(tail, next_text)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _resolve_semantic_threshold(
    *,
    similarities: list[float],
    threshold_mode: SemanticThresholdMode,
    breakpoint_percentile: int | None,
    fixed_threshold: float | None,
) -> float | None:
    percentile_value: float | None = None
    if similarities and breakpoint_percentile is not None:
        percentile_value = _percentile(similarities, breakpoint_percentile)

    if threshold_mode == SemanticThresholdMode.PERCENTILE:
        return percentile_value
    if threshold_mode == SemanticThresholdMode.FIXED:
        return fixed_threshold

    candidates = [
        value for value in (percentile_value, fixed_threshold) if value is not None
    ]
    if not candidates:
        return None
    return min(candidates)


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0

    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    p = min(max(float(percentile), 0.0), 100.0) / 100.0
    pos = p * (len(sorted_values) - 1)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(sorted_values[lower])

    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    weight = pos - lower
    return float(lower_value + (upper_value - lower_value) * weight)


def _enforce_semantic_max_tokens(
    chunks: list[str],
    *,
    max_tokens: int,
    overlap_chars: int,
    tokenizer_model: str | None,
) -> list[str]:
    bounded_chunks: list[str] = []
    max_tokens = max(max_tokens, 1)

    for chunk in chunks:
        chunk_text = (chunk or "").strip()
        if not chunk_text:
            continue
        if count_tokens(chunk_text, model=tokenizer_model) <= max_tokens:
            bounded_chunks.append(chunk_text)
            continue

        overlap_tokens = 0
        if overlap_chars > 0:
            overlap_tokens = count_tokens(
                chunk_text[-overlap_chars:], model=tokenizer_model
            )
            overlap_tokens = max(0, min(overlap_tokens, max_tokens - 1))

        pieces = split_text_to_token_budget(
            chunk_text,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            model=tokenizer_model,
        )
        if not pieces:
            bounded_chunks.append(chunk_text)
            continue

        for piece in pieces:
            stripped = piece.strip()
            if stripped:
                bounded_chunks.append(stripped)

    return bounded_chunks


def _aggregate_pdf_blocks_by_tokens(
    blocks: list[ParsedChunk],
    *,
    chunk_size_tokens: int,
    overlap_tokens: int,
    tokenizer_model: str | None,
) -> list[ParsedChunk]:
    if not blocks:
        return []

    chunk_size_tokens = max(int(chunk_size_tokens), 1)
    overlap_tokens = max(int(overlap_tokens), 0)
    token_counts = [
        max(count_tokens((block.text or "").strip(), model=tokenizer_model), 0)
        for block in blocks
    ]

    aggregated: list[ParsedChunk] = []
    idx = 0
    while idx < len(blocks):
        current_text_parts: list[str] = []
        current_blocks: list[dict[str, object]] = []
        current_types: list[str] = []
        page_start: int | None = None
        page_end: int | None = None

        token_total = 0
        j = idx
        while j < len(blocks) and token_total < chunk_size_tokens:
            block = blocks[j]
            text = (block.text or "").strip()
            if text:
                current_text_parts.append(text)
                token_total += max(token_counts[j], 1)

            locator = block.locator or {}
            blocks_list = locator.get("blocks") if isinstance(locator, dict) else None
            if isinstance(blocks_list, list) and blocks_list:
                current_blocks.extend(blocks_list)
            if isinstance(locator, dict):
                if page_start is None:
                    page_start = locator.get("page_start")
                page_end = locator.get("page_end", page_start)

            block_type = (block.metadata or {}).get("mineru_block_type")
            if isinstance(block_type, str):
                current_types.append(block_type)
            j += 1

        if current_text_parts:
            locator = {
                "kind": "pdf",
                "page_start": page_start,
                "page_end": page_end,
                "blocks": current_blocks,
            }
            metadata: dict[str, object] = {}
            if current_types:
                metadata["mineru_block_types"] = current_types
            aggregated.append(
                ParsedChunk(
                    text="\n\n".join(current_text_parts).strip(),
                    locator=locator,
                    metadata=metadata or None,
                )
            )

        if overlap_tokens > 0:
            overlap_total = 0
            back = j - 1
            overlap_blocks = 0
            while back >= idx and overlap_total < overlap_tokens:
                overlap_total += max(token_counts[back], 0)
                overlap_blocks += 1
                back -= 1
            idx = max(j - overlap_blocks, idx + 1)
        else:
            idx = j

    return aggregated


def _aggregate_pdf_blocks(
    blocks: list[ParsedChunk], chunk_size: int, overlap_chars: int
) -> list[ParsedChunk]:
    if not blocks:
        return []

    aggregated: list[ParsedChunk] = []
    idx = 0
    while idx < len(blocks):
        current_text_parts: list[str] = []
        current_blocks: list[dict[str, object]] = []
        current_types: list[str] = []
        page_start: int | None = None
        page_end: int | None = None

        length = 0
        j = idx
        while j < len(blocks) and length < chunk_size:
            block = blocks[j]
            text = (block.text or "").strip()
            if text:
                current_text_parts.append(text)
                length += len(text)
            locator = block.locator or {}
            blocks_list = locator.get("blocks") if isinstance(locator, dict) else None
            if isinstance(blocks_list, list) and blocks_list:
                current_blocks.extend(blocks_list)
            if isinstance(locator, dict):
                if page_start is None:
                    page_start = locator.get("page_start")
                page_end = locator.get("page_end", page_start)
            block_type = (block.metadata or {}).get("mineru_block_type")
            if isinstance(block_type, str):
                current_types.append(block_type)
            j += 1

        if current_text_parts:
            locator = {
                "kind": "pdf",
                "page_start": page_start,
                "page_end": page_end,
                "blocks": current_blocks,
            }
            metadata: dict[str, object] = {}
            if current_types:
                metadata["mineru_block_types"] = current_types
            aggregated.append(
                ParsedChunk(
                    text="\n\n".join(current_text_parts).strip(),
                    locator=locator,
                    metadata=metadata or None,
                )
            )

        if overlap_chars > 0:
            overlap_len = 0
            back = j - 1
            overlap_blocks = 0
            while back >= idx and overlap_len < overlap_chars:
                overlap_len += len((blocks[back].text or "").strip())
                overlap_blocks += 1
                back -= 1
            idx = max(j - overlap_blocks, idx + 1)
        else:
            idx = j

    return aggregated
