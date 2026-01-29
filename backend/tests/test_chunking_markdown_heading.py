import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services.chunking import ChunkingEngine
from app.services.parsing.types import ParsedDocument


@pytest.mark.asyncio
async def test_markdown_heading_split_does_not_cross_sections_and_emits_heading_path() -> None:
    # Two headings, both long enough to trigger stage-2 splitting.
    md = (
        "# A\n\n"
        "SECTION_A\n"
        + ("a" * 600)
        + "\n\n# B\n\n"
        "SECTION_B\n"
        + ("b" * 600)
    )
    doc = ParsedDocument(text=md, mime_type="text/markdown")
    index_config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "markdown_heading",
                "markdown_heading": {
                    "max_heading_level": 1,
                    "chunk_size": 200,
                    "chunk_overlap": 0,
                },
            },
            "contextual": {"enabled": False},
        }
    )

    items = await ChunkingEngine().split(doc, index_config)
    assert items

    a_items = [it for it in items if (it.metadata or {}).get("heading_path") == "A"]
    b_items = [it for it in items if (it.metadata or {}).get("heading_path") == "B"]
    assert a_items and b_items

    # Stage 2 must not cross section boundaries.
    for it in a_items:
        assert "SECTION_B" not in it.content
    for it in b_items:
        assert "SECTION_A" not in it.content
