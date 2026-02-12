"""DocumentChunk persistence helpers."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.services.chunking import ChunkItem
from app.utils.token_counter import count_tokens


class ChunkPersistenceService:
    """Persist chunking outputs into PostgreSQL document_chunks."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def _resolve_embedding_texts(
        *,
        chunk_items: Sequence[ChunkItem],
        embedding_texts: Sequence[str] | None,
    ) -> list[str]:
        if embedding_texts is None:
            return [str(item.content or "") for item in chunk_items]
        if len(embedding_texts) != len(chunk_items):
            raise ValueError("embedding_texts length must match chunk_items length")
        return [str(text) if text is not None else "" for text in embedding_texts]

    @staticmethod
    def _resolve_optional_strings(
        *,
        values: Sequence[str | None] | None,
        expected_len: int,
        field_name: str,
    ) -> list[str | None]:
        if values is None:
            return [None] * expected_len
        if len(values) != expected_len:
            raise ValueError(f"{field_name} length must match chunk_items length")
        resolved: list[str | None] = []
        for value in values:
            if value is None:
                resolved.append(None)
            else:
                raw = str(value).strip()
                resolved.append(raw or None)
        return resolved

    @staticmethod
    def _resolve_context_statuses(
        *,
        values: Sequence[str] | None,
        expected_len: int,
    ) -> list[str]:
        if values is None:
            return ["not_enabled"] * expected_len
        if len(values) != expected_len:
            raise ValueError("context_statuses length must match chunk_items length")
        resolved: list[str] = []
        for value in values:
            item = str(value or "").strip() or "not_enabled"
            resolved.append(item)
        return resolved

    @staticmethod
    def _resolve_context_attempts(
        *,
        values: Sequence[int] | None,
        expected_len: int,
    ) -> list[int]:
        if values is None:
            return [0] * expected_len
        if len(values) != expected_len:
            raise ValueError("context_attempts length must match chunk_items length")
        return [max(int(value or 0), 0) for value in values]

    @staticmethod
    def _resolve_chunking_strategy(chunk_item: ChunkItem) -> str:
        metadata = chunk_item.metadata if isinstance(chunk_item.metadata, dict) else {}
        raw_strategy = metadata.get("chunking_strategy")
        if isinstance(raw_strategy, str):
            strategy = raw_strategy.strip()
            if strategy:
                return strategy
        return "unknown"

    @staticmethod
    def _resolve_heading_path(chunk_item: ChunkItem) -> str | None:
        metadata = chunk_item.metadata if isinstance(chunk_item.metadata, dict) else {}
        raw_heading_path = metadata.get("heading_path")
        if not isinstance(raw_heading_path, str):
            return None
        heading_path = raw_heading_path.strip()
        return heading_path or None

    @staticmethod
    def _resolve_int_from_metadata(chunk_item: ChunkItem, key: str) -> int | None:
        metadata = chunk_item.metadata if isinstance(chunk_item.metadata, dict) else {}
        value = metadata.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _resolve_source_kind(chunk_item: ChunkItem) -> str | None:
        locator = chunk_item.locator if isinstance(chunk_item.locator, dict) else {}
        kind = locator.get("kind")
        if isinstance(kind, str):
            normalized = kind.strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _resolve_source_page(chunk_item: ChunkItem, key: str) -> int | None:
        locator = chunk_item.locator if isinstance(chunk_item.locator, dict) else {}
        value = locator.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    async def replace_material_chunks(
        self,
        *,
        kb_id: uuid.UUID,
        material_id: uuid.UUID,
        chunk_items: Sequence[ChunkItem],
        chunk_ids: Sequence[uuid.UUID] | None = None,
        embedding_texts: Sequence[str] | None = None,
        context_texts: Sequence[str | None] | None = None,
        context_statuses: Sequence[str] | None = None,
        context_errors: Sequence[str | None] | None = None,
        context_attempts: Sequence[int] | None = None,
    ) -> list[uuid.UUID]:
        """Replace all chunks for a material in one transaction scope."""
        if chunk_ids is not None and len(chunk_ids) != len(chunk_items):
            raise ValueError("chunk_ids length must match chunk_items length")

        await self._db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.kb_id == kb_id,
                DocumentChunk.material_id == material_id,
            )
        )

        if not chunk_items:
            return []

        resolved_chunk_ids = (
            list(chunk_ids)
            if chunk_ids is not None
            else [uuid.uuid4() for _ in chunk_items]
        )
        resolved_embedding_texts = self._resolve_embedding_texts(
            chunk_items=chunk_items,
            embedding_texts=embedding_texts,
        )
        total = len(chunk_items)
        resolved_context_texts = self._resolve_optional_strings(
            values=context_texts,
            expected_len=total,
            field_name="context_texts",
        )
        resolved_context_errors = self._resolve_optional_strings(
            values=context_errors,
            expected_len=total,
            field_name="context_errors",
        )
        resolved_context_statuses = self._resolve_context_statuses(
            values=context_statuses,
            expected_len=total,
        )
        resolved_context_attempts = self._resolve_context_attempts(
            values=context_attempts,
            expected_len=total,
        )

        rows: list[dict] = []
        for idx, chunk_item in enumerate(chunk_items):
            raw_text = str(chunk_item.content or "")
            rows.append(
                {
                    "id": resolved_chunk_ids[idx],
                    "kb_id": kb_id,
                    "material_id": material_id,
                    "chunk_index": idx,
                    "raw_text": raw_text,
                    "embedding_text": resolved_embedding_texts[idx],
                    "context_text": resolved_context_texts[idx],
                    "context_status": resolved_context_statuses[idx],
                    "context_error": resolved_context_errors[idx],
                    "context_attempts": resolved_context_attempts[idx],
                    "chunking_strategy": self._resolve_chunking_strategy(chunk_item),
                    "heading_path": self._resolve_heading_path(chunk_item),
                    "global_chunk_order": idx,
                    "window_id": self._resolve_int_from_metadata(chunk_item, "window_id"),
                    "window_size_tokens": self._resolve_int_from_metadata(
                        chunk_item,
                        "window_size_tokens",
                    ),
                    "window_overlap_tokens": self._resolve_int_from_metadata(
                        chunk_item,
                        "window_overlap_tokens",
                    ),
                    "token_start": self._resolve_int_from_metadata(chunk_item, "token_start"),
                    "token_end": self._resolve_int_from_metadata(chunk_item, "token_end"),
                    "source_kind": self._resolve_source_kind(chunk_item),
                    "source_page_start": self._resolve_source_page(chunk_item, "page_start"),
                    "source_page_end": self._resolve_source_page(chunk_item, "page_end"),
                    "locator": chunk_item.locator,
                    "content_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                    "token_count": count_tokens(raw_text),
                }
            )

        await self._db.execute(insert(DocumentChunk), rows)
        await self._db.flush()
        return resolved_chunk_ids
