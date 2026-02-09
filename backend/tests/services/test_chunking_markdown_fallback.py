import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services import chunking
from app.services.chunking import ChunkingEngine
from app.services.parsing.types import ParsedDocument


class _FakeMarkdownDoc:
    def __init__(self, page_content: str, metadata: dict) -> None:
        self.page_content = page_content
        self.metadata = metadata


class _NoHeadingSplitter:
    def __init__(self, *, headers_to_split_on) -> None:
        self.headers_to_split_on = headers_to_split_on

    def split_text(self, text: str):
        return [_FakeMarkdownDoc(text, {})]


@pytest.mark.asyncio
async def test_markdown_without_heading_falls_back_to_non_markdown_strategy(
    monkeypatch,
) -> None:
    monkeypatch.setattr(chunking, "MarkdownHeaderTextSplitter", _NoHeadingSplitter)
    monkeypatch.setattr(chunking, "RecursiveCharacterTextSplitter", None)

    engine = ChunkingEngine()
    doc = ParsedDocument(text=("纯文本没有标题。" * 30), mime_type="text/markdown")
    config = IndexConfig.model_validate(
        {
            "chunking": {
                "general_strategy": "markdown_heading",
                "sliding_window": {"chunk_size": 128, "chunk_overlap": 16},
                "markdown_heading": {
                    "max_heading_level": 3,
                    "chunk_size": 256,
                    "chunk_overlap": 16,
                },
            }
        }
    )

    items = await engine.split(doc, config)

    assert items
    assert all(item.metadata.get("chunking_strategy") == "sliding_window" for item in items)
