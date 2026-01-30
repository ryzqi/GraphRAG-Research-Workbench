"""Shared helpers for building embedding input texts in worker tasks.

We want ingestion and index_rebuild to produce identical embedding inputs for the same
chunk items, to avoid retrieval quality drift after a rebuild.

This module is intentionally dependency-light (duck-typed chunk items).
"""

from __future__ import annotations

from typing import Any, Sequence


def build_embedding_inputs(
    *,
    chunk_items: Sequence[Any],
    contexts: Sequence[str] | None,
    contextual_enabled: bool,
) -> list[str]:
    """Build embedding input strings for each chunk item.

    Rules:
    - If chunk_role == "child" and parent_ref is set, prefix with parent chunk content.
    - If metadata.heading_path is present, prefix with "heading_path : ".
    - If contextual_enabled and context is present, append "\n\n{context}".
    """

    if not chunk_items:
        return []

    ctx_list = list(contexts) if contexts is not None else []
    if len(ctx_list) < len(chunk_items):
        ctx_list.extend([""] * (len(chunk_items) - len(ctx_list)))

    parent_content_by_ref: dict[int, str] = {}
    parent_idx = 0
    for item in chunk_items:
        if getattr(item, "chunk_role", None) == "parent":
            parent_content_by_ref[parent_idx] = str(getattr(item, "content", "") or "")
            parent_idx += 1

    embedding_inputs: list[str] = []
    for item, context in zip(chunk_items, ctx_list, strict=False):
        base_text = str(getattr(item, "content", "") or "")

        chunk_role = getattr(item, "chunk_role", None)
        parent_ref = getattr(item, "parent_ref", None)
        if chunk_role == "child" and parent_ref is not None:
            parent_text = parent_content_by_ref.get(int(parent_ref))
            if parent_text:
                base_text = f"{parent_text}\n\n{base_text}"

        heading_path = None
        metadata = getattr(item, "metadata", None)
        if isinstance(metadata, dict):
            raw_heading_path = metadata.get("heading_path")
            if isinstance(raw_heading_path, str) and raw_heading_path.strip():
                heading_path = raw_heading_path.strip()
        if heading_path:
            base_text = f"{heading_path} : {base_text}"

        ctx = str(context or "")
        if contextual_enabled and ctx:
            embedding_inputs.append(f"{base_text}\n\n{ctx}")
        else:
            embedding_inputs.append(base_text)

    return embedding_inputs
