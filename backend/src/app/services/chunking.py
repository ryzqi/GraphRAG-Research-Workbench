"""Chunking strategies and engine."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.core.settings import Settings, get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig
from app.services.parsing.types import ParsedChunk, ParsedDocument
from app.utils.token_counter import count_tokens_approximately

try:  # pragma: no cover
    from langchain_text_splitters import MarkdownHeaderTextSplitter
except Exception:  # pragma: no cover
    MarkdownHeaderTextSplitter = None  # type: ignore

logger = logging.getLogger(__name__)

_SENTENCE_DELIMS = set("。！？!?")


@dataclass(slots=True)
class ChunkItem:
    content: str
    locator: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    chunk_role: str = "default"
    parent_ref: int | None = None
    child_seq: int | None = None


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
            chunk_size = index_config.chunking.sliding_window.chunk_size
            overlap = index_config.chunking.sliding_window.chunk_overlap
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
        if _is_markdown(document) and index_config.chunking.markdown_heading.enabled:
            md_chunks, used_headings = await self._split_markdown_heading(
                document, index_config
            )
            if used_headings:
                return md_chunks

        strategy = index_config.chunking.general_strategy
        if strategy == ChunkingStrategy.PARENT_CHILD:
            return await self._split_parent_child(document, index_config)
        if strategy == ChunkingStrategy.MAX_MIN_SEMANTIC:
            chunks = await self._split_semantic(document.text or "", index_config)
            return _wrap_chunks(
                chunks,
                document,
                chunking_strategy="max_min_semantic",
            )
        return _wrap_chunks(
            _split_sliding_window(
                document.text or "",
                index_config.chunking.sliding_window.chunk_size,
                index_config.chunking.sliding_window.chunk_overlap,
            ),
            document,
            chunking_strategy="sliding_window",
        )

    async def _split_semantic(
        self, text: str, index_config: IndexConfig
    ) -> list[str]:
        sentences = _split_sentences(text)
        if not sentences:
            return []

        embedding = self._embedding or EmbeddingClient()
        self._embedding = embedding

        try:
            vectors = await embedding.embed(texts=sentences)
        except Exception as exc:
            logger.warning(
                "Semantic chunking failed, fallback to sliding window",
                extra={"error": str(exc)},
            )
            return _split_sliding_window(
                text,
                index_config.chunking.sliding_window.chunk_size,
                index_config.chunking.sliding_window.chunk_overlap,
            )

        min_tokens = max(index_config.chunking.semantic.min_tokens, 1)
        max_tokens = max(index_config.chunking.semantic.max_tokens, min_tokens)
        threshold = index_config.chunking.semantic.similarity_threshold
        overlap_chars = max(index_config.chunking.semantic.overlap_chars, 0)

        chunks: list[str] = []
        current = sentences[0]
        current_tokens = count_tokens_approximately(current)

        for idx in range(1, len(sentences)):
            sentence = sentences[idx]
            sentence_tokens = count_tokens_approximately(sentence)
            sim = _cosine_similarity(vectors[idx - 1], vectors[idx])

            if current_tokens + sentence_tokens > max_tokens:
                chunks.append(current.strip())
                current = _apply_overlap(chunks[-1], sentence, overlap_chars)
                current_tokens = count_tokens_approximately(current)
                continue

            if sim < threshold and current_tokens >= min_tokens:
                chunks.append(current.strip())
                current = _apply_overlap(chunks[-1], sentence, overlap_chars)
                current_tokens = count_tokens_approximately(current)
                continue

            current = _merge_text(current, sentence)
            current_tokens += sentence_tokens

        if current.strip():
            chunks.append(current.strip())

        return chunks

    async def _split_markdown_heading(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> tuple[list[ChunkItem], bool]:
        if not document.text:
            return [], False
        if MarkdownHeaderTextSplitter is None:
            logger.warning(
                "MarkdownHeaderTextSplitter not available, fallback to general strategy"
            )
            return [], False

        max_level = index_config.chunking.markdown_heading.max_heading_level
        headers = [("#" * level, f"h{level}") for level in range(1, max_level + 1)]
        splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
        docs = splitter.split_text(document.text)

        if not docs:
            return [], False

        has_headings = any(getattr(doc, "metadata", {}) for doc in docs)
        if not has_headings:
            return [], False

        max_section_chars = index_config.chunking.markdown_heading.max_section_chars
        overlap = index_config.chunking.sliding_window.chunk_overlap
        items: list[ChunkItem] = []

        for doc in docs:
            section = (getattr(doc, "page_content", "") or "").strip()
            if not section:
                continue
            meta = getattr(doc, "metadata", {}) or {}
            heading_path = _build_heading_path(meta, headers)
            base_meta = {"chunking_strategy": "markdown_heading"}
            if heading_path:
                base_meta["heading_path"] = heading_path
            if len(section) > max_section_chars:
                sub_chunks = _split_sliding_window(section, max_section_chars, overlap)
            else:
                sub_chunks = [section]
            for chunk in sub_chunks:
                items.append(
                    ChunkItem(
                        content=chunk,
                        locator=_merge_locators(document.locator, None),
                        metadata=_merge_metadata(document.metadata, base_meta),
                        chunk_role="default",
                    )
                )

        return items, True

    async def _split_parent_child(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        if _is_markdown(document) and index_config.chunking.markdown_heading.enabled:
            md_chunks, used_headings = await self._split_markdown_heading(
                document, index_config
            )
            if used_headings:
                parent_chunks = [
                    ChunkItem(
                        content=chunk.content,
                        locator=chunk.locator,
                        metadata=chunk.metadata,
                        chunk_role="parent",
                    )
                    for chunk in md_chunks
                ]
            else:
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
        else:
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


class TextChunker:
    """Compatibility wrapper for legacy ingestion."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding: EmbeddingClient | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._embedding = embedding

    async def split(self, text: str) -> list[str]:
        if not text:
            return []

        strategy = self._settings.ingestion_chunk_strategy
        if strategy == "max_min_semantic":
            return await _split_semantic_with_settings(text, self._settings, self._embedding)
        if strategy != "sliding_window":
            logger.warning(
                "Unknown chunking strategy, fallback to sliding window",
                extra={"strategy": strategy},
            )
        return _split_sliding_window(
            text,
            self._settings.ingestion_chunk_size,
            self._settings.ingestion_chunk_overlap,
        )


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in _SENTENCE_DELIMS or ch == "\n":
            sentence = "".join(buf).strip()
            if sentence:
                sentences.append(sentence)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        sentences.append(tail)
    return sentences


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


async def _split_semantic_with_settings(
    text: str, settings: Settings, embedding: EmbeddingClient | None
) -> list[str]:
    sentences = _split_sentences(text)
    if not sentences:
        return []

    embedder = embedding or EmbeddingClient()
    try:
        vectors = await embedder.embed(texts=sentences)
    except Exception as exc:
        logger.warning(
            "Semantic chunking failed, fallback to sliding window",
            extra={"error": str(exc)},
        )
        return _split_sliding_window(
            text, settings.ingestion_chunk_size, settings.ingestion_chunk_overlap
        )

    min_tokens = max(settings.ingestion_semantic_min_tokens, 1)
    max_tokens = max(settings.ingestion_semantic_max_tokens, min_tokens)
    threshold = settings.ingestion_semantic_similarity_threshold
    overlap_chars = max(settings.ingestion_chunk_overlap, 0)

    chunks: list[str] = []
    current = sentences[0]
    current_tokens = count_tokens_approximately(current)

    for idx in range(1, len(sentences)):
        sentence = sentences[idx]
        sentence_tokens = count_tokens_approximately(sentence)
        sim = _cosine_similarity(vectors[idx - 1], vectors[idx])

        if current_tokens + sentence_tokens > max_tokens:
            chunks.append(current.strip())
            current = _apply_overlap(chunks[-1], sentence, overlap_chars)
            current_tokens = count_tokens_approximately(current)
            continue

        if sim < threshold and current_tokens >= min_tokens:
            chunks.append(current.strip())
            current = _apply_overlap(chunks[-1], sentence, overlap_chars)
            current_tokens = count_tokens_approximately(current)
            continue

        current = _merge_text(current, sentence)
        current_tokens += sentence_tokens

    if current.strip():
        chunks.append(current.strip())

    return chunks


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
