from __future__ import annotations

import re
import uuid
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from collections.abc import Sequence

from sqlalchemy import select

from app.models.document_chunk import DocumentChunk
from app.models.source_material import SourceMaterial
from app.schemas.query_enhancement import QueryHitSource, QueryItem
from app.services.retrieval_service_contracts import (
    RetrievalResult,
    RetrievedChunk,
    RetrievalServiceProtocol,
)


class RetrievalContextMixin(RetrievalServiceProtocol):
    @staticmethod
    def _strip_file_extension(name: str) -> str:
        raw = (name or "").strip()
        if not raw:
            return ""
        stem = PurePosixPath(raw).stem
        if stem == raw:
            stem = PureWindowsPath(raw).stem
        return stem.strip() or raw

    @staticmethod
    def _normalize_citation_label(value: str) -> str:
        cleaned = value.replace("[", " ").replace("]", " ")
        normalized = " ".join(cleaned.split())
        return normalized.strip()

    @staticmethod
    def _extract_filename_from_locator(locator: dict | None) -> str | None:
        if not isinstance(locator, dict):
            return None
        raw = locator.get("filename")
        if not isinstance(raw, str):
            return None
        value = raw.strip()
        if not value:
            return None
        # 同时规范化 POSIX 与 Windows 风格的路径分隔符。
        value = value.replace("\\", "/")
        return value.rsplit("/", 1)[-1] or None

    @classmethod
    def _derive_citation_label(
        cls, *, locator: dict | None, material_title: str | None
    ) -> str:
        filename = cls._extract_filename_from_locator(locator)
        if filename:
            label = cls._normalize_citation_label(cls._strip_file_extension(filename))
            if label:
                return label

        if isinstance(material_title, str) and material_title.strip():
            label = cls._normalize_citation_label(
                cls._strip_file_extension(material_title.strip())
            )
            if label:
                return label

        return "material"

    async def _load_material_titles_by_id(
        self, material_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not material_ids or self._db is None:
            return {}
        stmt = select(SourceMaterial.id, SourceMaterial.title).where(
            SourceMaterial.id.in_(list(material_ids))
        )
        result = await self._db_execute(stmt)
        title_by_id: dict[uuid.UUID, str] = {}
        for row in result.all():
            material_id = row[0]
            title = row[1]
            if isinstance(title, str) and title.strip():
                title_by_id[material_id] = title.strip()
        return title_by_id

    async def _ensure_chunk_citation_labels(self, chunks: list[RetrievedChunk]) -> None:
        if not chunks:
            return
        material_ids = {chunk.material_id for chunk in chunks}
        title_by_id = await self._load_material_titles_by_id(material_ids)
        for chunk in chunks:
            locator = chunk.locator if isinstance(chunk.locator, dict) else {}
            label = self._derive_citation_label(
                locator=locator,
                material_title=title_by_id.get(chunk.material_id),
            )
            if not isinstance(chunk.locator, dict):
                chunk.locator = {}
            chunk.locator["citation_label"] = label

    async def _hydrate_chunks_from_postgres(self, chunks: list[RetrievedChunk]) -> None:
        """当 Milvus 命中结果缺少 output_fields 时，回填 chunk 字段。

        Prefer Milvus output_fields; only query Postgres when fields are missing.
        """

        if not chunks or self._db is None:
            return

        missing: set[uuid.UUID] = set()
        for c in chunks:
            missing_content = not c.content
            missing_locator = c.locator is None or c.locator == {}
            missing_position = (
                c.chunk_index is None
                or c.global_chunk_order is None
                or c.heading_path is None
            )
            if missing_content or missing_locator or missing_position:
                missing.add(c.id)
        if not missing:
            return

        stmt = select(
            DocumentChunk.id,
            DocumentChunk.raw_text,
            DocumentChunk.locator,
            DocumentChunk.chunk_index,
            DocumentChunk.heading_path,
            DocumentChunk.global_chunk_order,
        ).where(DocumentChunk.id.in_(list(missing)))
        result = await self._db_execute(stmt)
        by_id: dict[
            uuid.UUID,
            tuple[str, dict | None, int | None, str | None, int | None],
        ] = {
            row.id: (
                row.raw_text,
                row.locator,
                row.chunk_index,
                row.heading_path,
                row.global_chunk_order,
            )
            for row in result.all()
        }
        for c in chunks:
            got = by_id.get(c.id)
            if not got:
                continue
            text, locator, chunk_index, heading_path, global_chunk_order = got
            if not c.content:
                c.content = text or ""
            if (c.locator is None or c.locator == {}) and locator:
                c.locator = locator
            if c.chunk_index is None and isinstance(chunk_index, int):
                c.chunk_index = chunk_index
            if c.heading_path is None and isinstance(heading_path, str):
                c.heading_path = heading_path
            if c.global_chunk_order is None and isinstance(global_chunk_order, int):
                c.global_chunk_order = global_chunk_order

    @staticmethod
    def _first_markdown_heading_match(text: str) -> re.Match[str] | None:
        if not isinstance(text, str) or not text.strip():
            return None
        return re.search(r"(?m)^(#{2,6})\s+(.+?)\s*$", text)

    @classmethod
    def _first_markdown_heading(cls, text: str) -> tuple[int, str] | None:
        match = cls._first_markdown_heading_match(text)
        if match is None:
            return None
        return len(match.group(1)), match.group(2).strip()

    @staticmethod
    def _is_single_main_query(query_items: Sequence[QueryItem]) -> bool:
        if len(query_items) != 1:
            return False
        item = query_items[0]
        if not isinstance(item, dict):
            return False
        kind = str(item.get("kind") or "").strip().lower()
        query = str(item.get("query") or "").strip()
        return kind == "main" and bool(query)

    async def _expand_direct_section_neighbors(
        self,
        results: list[RetrievalResult],
        *,
        query_items: Sequence[QueryItem],
        top_n: int,
        timeout_seconds: float | None = None,
        hits_by_key: dict[tuple[str, str, str], list[QueryHitSource]] | None = None,
    ) -> list[RetrievalResult]:
        if (
            not results
            or self._db is None
            or not self._is_single_main_query(query_items)
        ):
            return results

        seed = results[0].chunk
        if (
            seed.global_chunk_order is None
            or seed.chunk_role == "child"
            or not isinstance(seed.content, str)
            or not seed.content.strip()
        ):
            return results

        heading = self._first_markdown_heading(seed.content)
        if heading is None:
            return results
        seed_level, _ = heading
        boundary_level = max(2, seed_level - 1)
        max_scan_rows = max(8, min(max(top_n * 2, top_n + 4), 24))

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.kb_id,
                DocumentChunk.material_id,
                DocumentChunk.raw_text,
                DocumentChunk.locator,
                DocumentChunk.chunk_index,
                DocumentChunk.heading_path,
                DocumentChunk.global_chunk_order,
            )
            .where(
                DocumentChunk.kb_id == seed.kb_id,
                DocumentChunk.material_id == seed.material_id,
                DocumentChunk.global_chunk_order >= int(seed.global_chunk_order),
                DocumentChunk.global_chunk_order
                <= int(seed.global_chunk_order) + max_scan_rows,
            )
            .order_by(DocumentChunk.global_chunk_order.asc())
        )

        rows = await self._run_with_timeout(self._db_execute(stmt), timeout_seconds)
        existing_ids = {row.chunk.id for row in results}
        expanded = list(results)
        after_seed = False
        section_parts = [seed.content.strip()]
        expansion_limit = max(top_n, 6)

        for row in rows.all():
            row_order = row.global_chunk_order
            if not isinstance(row_order, int):
                continue
            if row_order == seed.global_chunk_order:
                after_seed = True
                continue
            if not after_seed:
                continue

            text = row.raw_text or ""
            row_heading = self._first_markdown_heading(text)
            if row_heading is not None and row_heading[0] <= boundary_level:
                break
            if not text.strip():
                continue
            section_parts.append(text.strip())
            if row.id in existing_ids:
                continue
            if len(expanded) >= expansion_limit:
                continue

            chunk = RetrievedChunk(
                id=row.id,
                kb_id=row.kb_id,
                material_id=row.material_id,
                content=text,
                context=None,
                locator=row.locator,
                metadata=None,
                chunk_role="default",
                parent_chunk_id=None,
                child_seq=None,
                chunk_index=row.chunk_index
                if isinstance(row.chunk_index, int)
                else None,
                heading_path=row.heading_path
                if isinstance(row.heading_path, str)
                else None,
                global_chunk_order=row_order,
            )
            expanded.append(
                RetrievalResult(
                    chunk=chunk,
                    score=max(results[0].score - 0.001 * len(expanded), 0.0),
                    context_text=text,
                )
            )
            existing_ids.add(row.id)
            if isinstance(hits_by_key, dict):
                hits_by_key.setdefault(self._candidate_key(chunk), [])

        if len(section_parts) > 1:
            merged_section = "\n\n".join(part for part in section_parts if part)
            expanded[0].context_text = merged_section

        return expanded

    async def _populate_result_context_from_heading_path(
        self,
        result: RetrievalResult,
        *,
        timeout_seconds: float | None = None,
        scan_radius: int = 8,
    ) -> RetrievalResult:
        if self._db is None:
            return result

        seed = result.chunk
        seed_content = (seed.content or "").strip()
        existing_context = (result.context_text or "").strip()
        heading_path = str(seed.heading_path or "").strip()
        if (
            not seed_content
            or seed.global_chunk_order is None
            or seed.chunk_role == "child"
        ):
            return result
        if existing_context and len(existing_context) > len(seed_content):
            return result

        if not heading_path:
            radius = max(int(scan_radius), 1)
            stmt = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.kb_id,
                    DocumentChunk.material_id,
                    DocumentChunk.raw_text,
                    DocumentChunk.locator,
                    DocumentChunk.chunk_index,
                    DocumentChunk.heading_path,
                    DocumentChunk.global_chunk_order,
                )
                .where(
                    DocumentChunk.kb_id == seed.kb_id,
                    DocumentChunk.material_id == seed.material_id,
                    DocumentChunk.global_chunk_order
                    >= int(seed.global_chunk_order) - radius,
                    DocumentChunk.global_chunk_order <= int(seed.global_chunk_order),
                )
                .order_by(DocumentChunk.global_chunk_order.asc())
            )

            rows = await self._run_with_timeout(self._db_execute(stmt), timeout_seconds)
            ordered_rows = [
                row
                for row in rows.all()
                if isinstance(getattr(row, "global_chunk_order", None), int)
            ]
            if not ordered_rows:
                return result

            seed_index = next(
                (
                    index
                    for index, row in enumerate(ordered_rows)
                    if int(row.global_chunk_order) == int(seed.global_chunk_order)
                ),
                None,
            )
            if seed_index is None or seed_index <= 0:
                return result

            start_index: int | None = None
            start_match: re.Match[str] | None = None
            for index in range(seed_index - 1, -1, -1):
                match = self._first_markdown_heading_match(
                    str(getattr(ordered_rows[index], "raw_text", "") or "")
                )
                if match is not None:
                    start_index = index
                    start_match = match
                    break
            if start_index is None or start_match is None:
                return result

            section_parts: list[str] = []
            for index in range(start_index, seed_index + 1):
                text = str(getattr(ordered_rows[index], "raw_text", "") or "")
                if index == start_index and start_match.start() > 0:
                    text = text[start_match.start() :]
                if index == seed_index:
                    end_match = self._first_markdown_heading_match(text)
                    if end_match is not None and end_match.start() > 0:
                        text = text[: end_match.start()]
                text = text.strip()
                if text:
                    section_parts.append(text)

            merged_section = "\n\n".join(section_parts).strip()
            if (
                not merged_section
                or merged_section == seed_content
                or seed_content not in merged_section
            ):
                return result

            result.context_text = merged_section
            return result

        radius = max(int(scan_radius), 1)
        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.kb_id,
                DocumentChunk.material_id,
                DocumentChunk.raw_text,
                DocumentChunk.locator,
                DocumentChunk.chunk_index,
                DocumentChunk.heading_path,
                DocumentChunk.global_chunk_order,
            )
            .where(
                DocumentChunk.kb_id == seed.kb_id,
                DocumentChunk.material_id == seed.material_id,
                DocumentChunk.global_chunk_order
                >= int(seed.global_chunk_order) - radius,
                DocumentChunk.global_chunk_order
                <= int(seed.global_chunk_order) + radius,
            )
            .order_by(DocumentChunk.global_chunk_order.asc())
        )

        rows = await self._run_with_timeout(self._db_execute(stmt), timeout_seconds)
        ordered_rows = [
            row
            for row in rows.all()
            if isinstance(getattr(row, "global_chunk_order", None), int)
        ]
        if not ordered_rows:
            return result

        seed_index = next(
            (
                index
                for index, row in enumerate(ordered_rows)
                if int(row.global_chunk_order) == int(seed.global_chunk_order)
            ),
            None,
        )
        if seed_index is None:
            return result

        def _same_heading_path(row: Any) -> bool:
            return str(getattr(row, "heading_path", "") or "").strip() == heading_path

        start = seed_index
        while start > 0 and _same_heading_path(ordered_rows[start - 1]):
            start -= 1
        end = seed_index
        while end + 1 < len(ordered_rows) and _same_heading_path(ordered_rows[end + 1]):
            end += 1

        section_parts = [
            str(getattr(row, "raw_text", "") or "").strip()
            for row in ordered_rows[start : end + 1]
            if str(getattr(row, "raw_text", "") or "").strip()
        ]
        if not section_parts:
            return result

        merged_section = "\n\n".join(section_parts).strip()
        if not merged_section or merged_section == seed_content:
            return result

        result.context_text = merged_section
        return result
