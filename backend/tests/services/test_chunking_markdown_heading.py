from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas.knowledge_bases import IndexConfig
from app.services import chunking as chunking_module
from app.services.chunking import ChunkingEngine
from app.services.parsing.types import ParsedDocument


class _FakeHeadingSplitter:
    def __init__(self, *, headers_to_split_on: list[tuple[str, str]]) -> None:
        self.headers_to_split_on = headers_to_split_on

    def split_text(self, text: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                page_content='Body content',
                metadata={'h1': 'Title 1', 'h2': 'Title 2'},
            )
        ]


class _FakeLongHeadingSplitter:
    def __init__(self, *, headers_to_split_on: list[tuple[str, str]]) -> None:
        self.headers_to_split_on = headers_to_split_on

    def split_text(self, text: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                page_content='a' * 220,
                metadata={'h1': 'Long Title'},
            )
        ]


@pytest.mark.asyncio
async def test_markdown_heading_chunk_prefixes_heading_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunking_module, 'MarkdownHeaderTextSplitter', _FakeHeadingSplitter)
    monkeypatch.setattr(chunking_module, 'RecursiveCharacterTextSplitter', None)

    engine = ChunkingEngine()
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'markdown_heading',
                'markdown_heading': {
                    'max_heading_level': 3,
                    'chunk_size': 4000,
                    'chunk_overlap': 200,
                },
            }
        }
    )

    chunks = await engine.split(ParsedDocument(text='# ignored'), index_config)

    assert len(chunks) == 1
    assert chunks[0].content == '# Title 1\n## Title 2\nBody content'
    assert chunks[0].metadata == {
        'chunking_strategy': 'markdown_heading',
        'heading_path': 'Title 1 > Title 2',
    }


@pytest.mark.asyncio
async def test_markdown_heading_prefix_applies_to_each_sub_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunking_module, 'MarkdownHeaderTextSplitter', _FakeLongHeadingSplitter)
    monkeypatch.setattr(chunking_module, 'RecursiveCharacterTextSplitter', None)

    engine = ChunkingEngine()
    index_config = IndexConfig.model_validate(
        {
            'chunking': {
                'general_strategy': 'markdown_heading',
                'markdown_heading': {
                    'max_heading_level': 2,
                    'chunk_size': 200,
                    'chunk_overlap': 0,
                },
            }
        }
    )

    chunks = await engine.split(ParsedDocument(text='# ignored'), index_config)

    assert len(chunks) == 2
    assert all(chunk.content.startswith('# Long Title\n') for chunk in chunks)
