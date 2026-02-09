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

    async def replace_material_chunks(
        self,
        *,
        kb_id: uuid.UUID,
        material_id: uuid.UUID,
        chunk_items: Sequence[ChunkItem],
        chunk_ids: Sequence[uuid.UUID] | None = None,
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

        rows: list[dict] = []
        for idx, chunk_item in enumerate(chunk_items):
            text = chunk_item.content
            rows.append(
                {
                    "id": resolved_chunk_ids[idx],
                    "kb_id": kb_id,
                    "material_id": material_id,
                    "chunk_index": idx,
                    "text": text,
                    "locator": chunk_item.locator,
                    "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "token_count": None,
                }
            )

        await self._db.execute(insert(DocumentChunk), rows)
        await self._db.flush()
        return resolved_chunk_ids
