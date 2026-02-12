"""Chunking strategies and engine."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from app.core.settings import Settings, get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.schemas.knowledge_bases import (
    ChunkingStrategy,
    IndexConfig,
    SemanticThresholdMode,
)
from app.services.parsing.types import ParsedChunk, ParsedDocument
from app.utils.token_counter import (
    count_tokens,
    split_text_by_token_windows,
    split_text_to_token_budget,
)

try:  # pragma: no cover
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )
except Exception:  # pragma: no cover
    MarkdownHeaderTextSplitter = None  # type: ignore
    RecursiveCharacterTextSplitter = None  # type: ignore

logger = logging.getLogger(__name__)

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


@dataclass(slots=True)
class ChunkItem:
    content: str
    locator: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    chunk_role: str = "default"
    parent_ref: int | None = None
    child_seq: int | None = None


@dataclass(slots=True)
class SemanticSplitResult:
    chunks: list[str]
    threshold_mode: str
    threshold_used: float | None
    semantic_fallback: bool = False
    semantic_fallback_reason: str | None = None
    fallback_window_size_tokens: int | None = None
    fallback_window_overlap_tokens: int | None = None


class ChunkingEngine:
    """Chunking engine for ParsedDocument + IndexConfig."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding: EmbeddingClient | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._embedding = embedding

    async def split(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        if not document.text and not document.chunks:
            return []

        if _is_pdf_blocks(document):
            strategy = index_config.chunking.general_strategy
            if strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                return self._split_pdf_query_dependent_multiscale(document, index_config)
            if strategy == ChunkingStrategy.MAX_MIN_SEMANTIC:
                return await self._split_pdf_semantic(document, index_config)

            chunk_size, overlap = _first_query_dependent_multiscale_window_chars(index_config)
            aggregated = _aggregate_pdf_blocks(document.chunks or [], chunk_size, overlap)
            items: list[ChunkItem] = []
            for block in aggregated:
                sub_doc = ParsedDocument(
                    text=block.text,
                    mime_type=document.mime_type,
                    locator=_merge_locators(document.locator, block.locator),
                    metadata=_merge_metadata(document.metadata, block.metadata),
                )
                items.extend(await self._split_general(sub_doc, index_config))
            return items

        return await self._split_general(document, index_config)

    async def _split_general(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        strategy = index_config.chunking.general_strategy
        if strategy == ChunkingStrategy.MARKDOWN_HEADING:
            return await self._split_markdown_heading(document, index_config)
        return await self._split_non_markdown_general(document, index_config)

    async def _split_non_markdown_general(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        strategy = index_config.chunking.general_strategy
        if strategy == ChunkingStrategy.PARENT_CHILD:
            return await self._split_parent_child(document, index_config)
        if strategy == ChunkingStrategy.MAX_MIN_SEMANTIC:
            result = await self._split_semantic(document.text or "", index_config)
            return _wrap_semantic_chunks(result=result, document=document)
        return self._split_query_dependent_multiscale(document, index_config)

    def _split_query_dependent_multiscale(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        text = document.text or ""
        items: list[ChunkItem] = []
        tokenizer_model = self._settings.embedding_model

        for window_id, window in enumerate(
            index_config.chunking.query_dependent_multiscale.windows
        ):
            chunks = _split_sliding_window_by_tokens(
                text,
                chunk_size_tokens=window.chunk_size_tokens,
                chunk_overlap_tokens=window.chunk_overlap_tokens,
                model=tokenizer_model,
            )
            for chunk_index, chunk in enumerate(chunks):
                metadata = {
                    "chunking_strategy": "query_dependent_multiscale",
                    "window_id": window_id,
                    "window_size_tokens": window.chunk_size_tokens,
                    "window_overlap_tokens": window.chunk_overlap_tokens,
                    "token_start": chunk["token_start"],
                    "token_end": chunk["token_end"],
                    "index": chunk_index,
                }
                locator = {
                    "window_id": window_id,
                    "token_start": chunk["token_start"],
                    "token_end": chunk["token_end"],
                    "index": chunk_index,
                }
                items.append(
                    ChunkItem(
                        content=chunk["text"],
                        locator=_merge_locators(document.locator, locator),
                        metadata=_merge_metadata(document.metadata, metadata),
                    )
                )

        return items

    def _split_pdf_query_dependent_multiscale(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        items: list[ChunkItem] = []
        blocks = document.chunks or []
        tokenizer_model = self._settings.embedding_model

        for window_id, window in enumerate(
            index_config.chunking.query_dependent_multiscale.windows
        ):
            aggregated = _aggregate_pdf_blocks_by_tokens(
                blocks,
                chunk_size_tokens=window.chunk_size_tokens,
                overlap_tokens=window.chunk_overlap_tokens,
                tokenizer_model=tokenizer_model,
            )
            step_tokens = max(
                window.chunk_size_tokens - window.chunk_overlap_tokens,
                1,
            )
            token_cursor = 0
            for chunk_index, block in enumerate(aggregated):
                token_count = max(count_tokens(block.text, model=tokenizer_model), 1)
                metadata = {
                    "chunking_strategy": "query_dependent_multiscale",
                    "window_id": window_id,
                    "window_size_tokens": window.chunk_size_tokens,
                    "window_overlap_tokens": window.chunk_overlap_tokens,
                    "token_start": token_cursor,
                    "token_end": token_cursor + token_count,
                    "index": chunk_index,
                }
                locator = {
                    "window_id": window_id,
                    "token_start": token_cursor,
                    "token_end": token_cursor + token_count,
                    "index": chunk_index,
                }
                items.append(
                    ChunkItem(
                        content=block.text,
                        locator=_merge_locators(
                            _merge_locators(document.locator, block.locator),
                            locator,
                        ),
                        metadata=_merge_metadata(
                            _merge_metadata(document.metadata, block.metadata),
                            metadata,
                        ),
                    )
                )
                token_cursor += step_tokens

        return items

    async def _split_pdf_semantic(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        semantic_cfg = index_config.chunking.semantic
        chunk_size_chars = max(semantic_cfg.max_tokens, 1) * _APPROX_TOKEN_CHARS
        overlap_chars = max(semantic_cfg.overlap_chars, 0)

        aggregated = _aggregate_pdf_blocks(
            document.chunks or [],
            chunk_size_chars,
            overlap_chars,
        )

        items: list[ChunkItem] = []
        for block in aggregated:
            sub_doc = ParsedDocument(
                text=block.text,
                mime_type=document.mime_type,
                locator=_merge_locators(document.locator, block.locator),
                metadata=_merge_metadata(document.metadata, block.metadata),
            )
            items.extend(await self._split_non_markdown_general(sub_doc, index_config))
        return items

    async def _split_semantic(
        self, text: str, index_config: IndexConfig
    ) -> SemanticSplitResult:
        semantic_cfg = index_config.chunking.semantic
        threshold_mode = semantic_cfg.threshold_mode.value
        tokenizer_model = self._settings.embedding_model

        sentences = _split_sentences(text)
        if not sentences:
            return SemanticSplitResult(
                chunks=[],
                threshold_mode=threshold_mode,
                threshold_used=None,
            )

        embedding = self._embedding or EmbeddingClient()
        self._embedding = embedding

        vectors: list[list[float]] = []
        batch_size = max(semantic_cfg.embedding_batch_size, 1)
        try:
            for start_idx in range(0, len(sentences), batch_size):
                batch = sentences[start_idx : start_idx + batch_size]
                vectors.extend(await embedding.embed(texts=batch))
        except Exception as exc:
            chunk_size_tokens, chunk_overlap_tokens = _first_query_dependent_multiscale_window(
                index_config
            )
            logger.warning(
                "Semantic chunking failed, fallback to first query-dependent multiscale window",
                extra={"error": str(exc)},
            )
            fallback_chunks = [
                str(chunk["text"])
                for chunk in _split_sliding_window_by_tokens(
                    text,
                    chunk_size_tokens=chunk_size_tokens,
                    chunk_overlap_tokens=chunk_overlap_tokens,
                    model=tokenizer_model,
                )
            ]
            return SemanticSplitResult(
                chunks=fallback_chunks,
                threshold_mode=threshold_mode,
                threshold_used=None,
                semantic_fallback=True,
                semantic_fallback_reason=type(exc).__name__,
                fallback_window_size_tokens=chunk_size_tokens,
                fallback_window_overlap_tokens=chunk_overlap_tokens,
            )

        min_tokens = max(semantic_cfg.min_tokens, 1)
        max_tokens = max(semantic_cfg.max_tokens, min_tokens)
        overlap_chars = max(semantic_cfg.overlap_chars, 0)
        threshold = _resolve_semantic_threshold(
            similarities=[
                _cosine_similarity(vectors[idx - 1], vectors[idx])
                for idx in range(1, len(vectors))
            ],
            threshold_mode=semantic_cfg.threshold_mode,
            breakpoint_percentile=semantic_cfg.breakpoint_percentile,
            fixed_threshold=semantic_cfg.similarity_threshold,
        )

        sentence_tokens = [
            max(count_tokens(sentence, model=tokenizer_model), 1)
            for sentence in sentences
        ]

        chunks: list[str] = []
        current = sentences[0].strip()
        current_tokens = sentence_tokens[0]

        for idx in range(1, len(sentences)):
            sentence = sentences[idx].strip()
            if not sentence:
                continue

            sentence_tokens_count = sentence_tokens[idx]
            sim = _cosine_similarity(vectors[idx - 1], vectors[idx])

            should_flush = False
            if current_tokens + sentence_tokens_count > max_tokens:
                should_flush = True
            elif (
                threshold is not None
                and sim < threshold
                and current_tokens >= min_tokens
            ):
                should_flush = True

            if should_flush:
                if current.strip():
                    chunks.append(current.strip())
                current = _apply_overlap(chunks[-1], sentence, overlap_chars) if chunks else sentence
                current_tokens = max(count_tokens(current, model=tokenizer_model), 1)
                continue

            current = _merge_text(current, sentence)
            current_tokens += sentence_tokens_count

        if current.strip():
            chunks.append(current.strip())

        final_chunks = _enforce_semantic_max_tokens(
            chunks,
            max_tokens=max_tokens,
            overlap_chars=overlap_chars,
            tokenizer_model=tokenizer_model,
        )

        return SemanticSplitResult(
            chunks=final_chunks,
            threshold_mode=threshold_mode,
            threshold_used=threshold,
        )

    async def _split_markdown_heading(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        if not document.text:
            return []
        if MarkdownHeaderTextSplitter is None:
            logger.warning(
                "MarkdownHeaderTextSplitter not available, fallback to non-markdown strategy"
            )
            return await self._split_non_markdown_general(document, index_config)

        max_level = index_config.chunking.markdown_heading.max_heading_level
        headers = [("#" * level, f"h{level}") for level in range(1, max_level + 1)]
        splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
        docs = splitter.split_text(document.text)

        if not docs:
            logger.info("Markdown 文档未识别到标题结构，回退非 Markdown 策略")
            return await self._split_non_markdown_general(document, index_config)

        has_heading_structure = False
        for doc in docs:
            meta = getattr(doc, "metadata", {}) or {}
            heading_path = _build_heading_path(meta, headers)
            if heading_path:
                has_heading_structure = True
                break
        if not has_heading_structure:
            logger.info("Markdown 文档无标题树，回退非 Markdown 策略")
            return await self._split_non_markdown_general(document, index_config)

        chunk_size = index_config.chunking.markdown_heading.chunk_size
        overlap = index_config.chunking.markdown_heading.chunk_overlap
        recursive_splitter = (
            RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
            if RecursiveCharacterTextSplitter is not None
            else None
        )
        items: list[ChunkItem] = []

        for doc in docs:
            section = (getattr(doc, "page_content", "") or "").strip()
            if not section:
                continue
            meta = getattr(doc, "metadata", {}) or {}
            heading_path = _build_heading_path(meta, headers)
            heading_prefix = _build_markdown_heading_prefix(meta, headers)
            base_meta = {"chunking_strategy": "markdown_heading"}
            if heading_path:
                base_meta["heading_path"] = heading_path

            # Stage 2: split *within* each section only (no cross-section boundaries).
            if len(section) > chunk_size:
                if recursive_splitter is not None:
                    sub_chunks = [c.strip() for c in recursive_splitter.split_text(section)]
                    sub_chunks = [c for c in sub_chunks if c]
                else:
                    sub_chunks = _split_sliding_window(section, chunk_size, overlap)
            else:
                sub_chunks = [section]
            for chunk in sub_chunks:
                content = chunk
                if heading_prefix:
                    content = f"{heading_prefix}\n{chunk}"
                items.append(
                    ChunkItem(
                        content=content,
                        locator=_merge_locators(document.locator, None),
                        metadata=_merge_metadata(document.metadata, base_meta),
                        chunk_role="default",
                    )
                )

        return items

    async def _split_parent_child(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        parent_chunks = _wrap_chunks(
            _split_sliding_window(
                document.text or "",
                index_config.chunking.parent_child.parent.chunk_size,
                index_config.chunking.parent_child.parent.chunk_overlap,
            ),
            document,
            chunking_strategy="parent_window",
            chunk_role="parent",
        )

        items: list[ChunkItem] = []
        items.extend(parent_chunks)

        child_size = index_config.chunking.parent_child.child.chunk_size
        child_overlap = index_config.chunking.parent_child.child.chunk_overlap

        for parent_idx, parent in enumerate(parent_chunks):
            child_chunks = _split_sliding_window(parent.content, child_size, child_overlap)
            for child_idx, child_text in enumerate(child_chunks):
                child_meta = _merge_metadata(
                    parent.metadata, {"chunking_strategy": "parent_child"}
                )
                items.append(
                    ChunkItem(
                        content=child_text,
                        locator=parent.locator,
                        metadata=child_meta,
                        chunk_role="child",
                        parent_ref=parent_idx,
                        child_seq=child_idx,
                    )
                )

        return items


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
    if len(token) == 1 and prev_char.isalpha() and isinstance(next_char, str) and next_char.isalpha():
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


def _first_query_dependent_multiscale_window(index_config: IndexConfig) -> tuple[int, int]:
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

    candidates = [value for value in (percentile_value, fixed_threshold) if value is not None]
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
            overlap_tokens = count_tokens(chunk_text[-overlap_chars:], model=tokenizer_model)
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


def _wrap_semantic_chunks(
    *,
    result: SemanticSplitResult,
    document: ParsedDocument,
) -> list[ChunkItem]:
    items: list[ChunkItem] = []
    for idx, chunk in enumerate(result.chunks):
        meta: dict[str, Any] = {
            "chunking_strategy": "max_min_semantic",
            "index": idx,
            "semantic_fallback": result.semantic_fallback,
            "threshold_mode": result.threshold_mode,
        }
        if result.threshold_used is not None:
            meta["threshold_used"] = result.threshold_used
        if result.semantic_fallback:
            if result.semantic_fallback_reason:
                meta["semantic_fallback_reason"] = result.semantic_fallback_reason
            if result.fallback_window_size_tokens is not None:
                meta["fallback_window_size_tokens"] = result.fallback_window_size_tokens
            if result.fallback_window_overlap_tokens is not None:
                meta["fallback_window_overlap_tokens"] = (
                    result.fallback_window_overlap_tokens
                )

        items.append(
            ChunkItem(
                content=chunk,
                locator=_merge_locators(document.locator, {"index": idx}),
                metadata=_merge_metadata(document.metadata, meta),
            )
        )

    return items


def _merge_locators(
    doc_locator: dict[str, Any] | None, chunk_locator: dict[str, Any] | None
) -> dict[str, Any] | None:
    if doc_locator is None and chunk_locator is None:
        return None
    merged: dict[str, Any] = {}
    if isinstance(doc_locator, dict):
        merged.update(doc_locator)
    if isinstance(chunk_locator, dict):
        merged.update(chunk_locator)
    return merged or None


def _merge_metadata(
    doc_meta: dict[str, Any] | None, chunk_meta: dict[str, Any] | None
) -> dict[str, Any] | None:
    if doc_meta is None and chunk_meta is None:
        return None
    merged: dict[str, Any] = {}
    if isinstance(doc_meta, dict):
        merged.update(doc_meta)
    if isinstance(chunk_meta, dict):
        merged.update(chunk_meta)
    return merged or None


def _is_markdown(document: ParsedDocument) -> bool:
    return (document.mime_type or "").lower() in {"text/markdown", "text/md", "markdown"}


def _is_pdf_blocks(document: ParsedDocument) -> bool:
    if not document.chunks:
        return False
    for chunk in document.chunks:
        locator = chunk.locator or {}
        if locator.get("kind") == "pdf":
            return True
    return False


def _wrap_chunks(
    chunks: list[str],
    document: ParsedDocument,
    *,
    chunking_strategy: str,
    chunk_role: str = "default",
) -> list[ChunkItem]:
    items: list[ChunkItem] = []
    for idx, chunk in enumerate(chunks):
        meta = {"chunking_strategy": chunking_strategy, "index": idx}
        items.append(
            ChunkItem(
                content=chunk,
                locator=_merge_locators(document.locator, {"index": idx}),
                metadata=_merge_metadata(document.metadata, meta),
                chunk_role=chunk_role,
            )
        )
    return items


def _build_heading_path(
    metadata: dict[str, Any], headers: list[tuple[str, str]]
) -> str | None:
    parts: list[str] = []
    for _, key in headers:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        return None
    return " > ".join(parts)


def _build_markdown_heading_prefix(
    metadata: dict[str, Any], headers: list[tuple[str, str]]
) -> str:
    lines: list[str] = []
    for marker, key in headers:
        value = metadata.get(key)
        if isinstance(value, str):
            title = value.strip()
            if title:
                lines.append(f"{marker} {title}")
    return "\n".join(lines)


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
        current_blocks: list[dict[str, Any]] = []
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
            locator: dict[str, Any] = {
                "kind": "pdf",
                "page_start": page_start,
                "page_end": page_end,
                "blocks": current_blocks,
            }
            metadata: dict[str, Any] = {}
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
        current_blocks: list[dict[str, Any]] = []
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
            locator: dict[str, Any] = {
                "kind": "pdf",
                "page_start": page_start,
                "page_end": page_end,
                "blocks": current_blocks,
            }
            metadata: dict[str, Any] = {}
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
