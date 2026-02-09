"""DocumentChunk persistence helpers."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.services.chunking import ChunkItem


class ChunkPersistenceService:
    """Persist chunking outputs into PostgreSQL document_chunks."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def _resolve_processed_texts(
        *,
        chunk_items: Sequence[ChunkItem],
        processed_texts: Sequence[str] | None,
    ) -> list[str]:
        if processed_texts is None:
            return [str(item.content or "") for item in chunk_items]
        if len(processed_texts) != len(chunk_items):
            raise ValueError("processed_texts length must match chunk_items length")
        return [str(text) if text is not None else "" for text in processed_texts]

    async def replace_material_chunks(
        self,
        *,
        kb_id: uuid.UUID,
        material_id: uuid.UUID,
        chunk_items: Sequence[ChunkItem],
        chunk_ids: Sequence[uuid.UUID] | None = None,
        processed_texts: Sequence[str] | None = None,
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
        resolved_processed_texts = self._resolve_processed_texts(
            chunk_items=chunk_items,
            processed_texts=processed_texts,
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
                    "text": raw_text,
                    "processed_text": resolved_processed_texts[idx],
                    "locator": chunk_item.locator,
                    "content_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                    "token_count": None,
                }
            )

        await self._db.execute(insert(DocumentChunk), rows)
        await self._db.flush()
        return resolved_chunk_ids
