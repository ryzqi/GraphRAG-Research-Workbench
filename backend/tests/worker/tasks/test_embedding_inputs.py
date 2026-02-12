from __future__ import annotations

from types import SimpleNamespace

from app.worker.tasks.embedding_inputs import build_embedding_inputs


def test_embedding_inputs_use_raw_chunk_when_context_empty() -> None:
    parent = SimpleNamespace(
        content="父分块",
        chunk_role="parent",
        parent_ref=None,
        metadata={},
    )
    child = SimpleNamespace(
        content="子分块",
        chunk_role="child",
        parent_ref=0,
        metadata={"heading_path": "一级/二级"},
    )

    outputs = build_embedding_inputs(
        chunk_items=[parent, child],
        contexts=["", ""],
        contextual_enabled=True,
    )

    assert outputs[0] == "父分块"
    assert outputs[1] == "一级/二级 : 父分块\n\n子分块"


def test_embedding_inputs_append_context_when_present() -> None:
    item = SimpleNamespace(
        content="原始分块",
        chunk_role="parent",
        parent_ref=None,
        metadata={},
    )

    outputs = build_embedding_inputs(
        chunk_items=[item],
        contexts=["增强上下文"],
        contextual_enabled=True,
    )

    assert outputs == ["原始分块\n\n增强上下文"]


def test_embedding_inputs_do_not_double_prefix_markdown_heading_chunks() -> None:
    item = SimpleNamespace(
        content='# Title 1\n## Title 2\nBody',
        chunk_role='default',
        parent_ref=None,
        metadata={
            'chunking_strategy': 'markdown_heading',
            'heading_path': 'Title 1 > Title 2',
        },
    )

    outputs = build_embedding_inputs(
        chunk_items=[item],
        contexts=[''],
        contextual_enabled=True,
    )

    assert outputs == ['# Title 1\n## Title 2\nBody']
