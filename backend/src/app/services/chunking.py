"""分块策略与分块引擎。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.settings import Settings, get_settings
from app.integrations.embedding_client import EmbeddingClient
from app.schemas.knowledge_bases import (
    ChunkingStrategy,
    IndexConfig,
)
from app.services.parsing.types import ParsedDocument
from app.services.chunking_algorithms import (
    _APPROX_TOKEN_CHARS,
    _aggregate_pdf_blocks,
    _aggregate_pdf_blocks_by_tokens,
    _apply_overlap,
    _cosine_similarity,
    _enforce_semantic_max_tokens,
    _first_query_dependent_multiscale_window,
    _first_query_dependent_multiscale_window_chars,
    _merge_text,
    _resolve_semantic_threshold,
    _split_sentences,
    _split_sliding_window,
    _split_sliding_window_by_tokens,
)
from app.utils.token_counter import count_tokens

try:  # pragma: no cover
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )
except Exception:  # pragma: no cover
    MarkdownHeaderTextSplitter = None  # type: ignore
    RecursiveCharacterTextSplitter = None  # type: ignore

logger = logging.getLogger(__name__)


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
    """面向 ParsedDocument + IndexConfig 的分块引擎。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding: EmbeddingClient | None = None,
        embedding_http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._embedding = embedding
        self._embedding_http_client = embedding_http_client

    async def split(
        self, document: ParsedDocument, index_config: IndexConfig
    ) -> list[ChunkItem]:
        if not document.text and not document.chunks:
            return []

        if _is_pdf_blocks(document):
            strategy = index_config.chunking.general_strategy
            if strategy == ChunkingStrategy.QUERY_DEPENDENT_MULTISCALE:
                return self._split_pdf_query_dependent_multiscale(
                    document, index_config
                )
            if strategy == ChunkingStrategy.MAX_MIN_SEMANTIC:
                return await self._split_pdf_semantic(document, index_config)

            chunk_size, overlap = _first_query_dependent_multiscale_window_chars(
                index_config
            )
            aggregated = _aggregate_pdf_blocks(
                document.chunks or [], chunk_size, overlap
            )
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
                        content=str(chunk["text"]),
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

        embedding = self._embedding or EmbeddingClient(
            http_client=self._embedding_http_client,
            settings=self._settings,
        )
        self._embedding = embedding

        vectors: list[list[float]] = []
        batch_size = max(semantic_cfg.embedding_batch_size, 1)
        try:
            for start_idx in range(0, len(sentences), batch_size):
                batch = sentences[start_idx : start_idx + batch_size]
                vectors.extend(await embedding.embed(texts=batch, stage="chunking"))
        except Exception as exc:
            chunk_size_tokens, chunk_overlap_tokens = (
                _first_query_dependent_multiscale_window(index_config)
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
                current = (
                    _apply_overlap(chunks[-1], sentence, overlap_chars)
                    if chunks
                    else sentence
                )
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

            # 第 2 阶段：仅在各 section 内部切分，不跨 section 边界。
            if len(section) > chunk_size:
                if recursive_splitter is not None:
                    sub_chunks = [
                        c.strip() for c in recursive_splitter.split_text(section)
                    ]
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
            child_chunks = _split_sliding_window(
                parent.content, child_size, child_overlap
            )
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
    return (document.mime_type or "").lower() in {
        "text/markdown",
        "text/md",
        "markdown",
    }


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
