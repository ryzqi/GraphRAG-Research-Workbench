from types import SimpleNamespace

from app.worker.tasks.embedding_inputs import build_embedding_inputs


def test_build_embedding_inputs_injects_heading_path_prefix() -> None:
    # Used by markdown_heading strategy chunks which emit metadata.heading_path.
    item = SimpleNamespace(
        content="chunk",
        metadata={"heading_path": "A > B"},
        chunk_role="default",
        parent_ref=None,
    )
    assert build_embedding_inputs(
        chunk_items=[item], contexts=None, contextual_enabled=False
    ) == ["A > B : chunk"]


def test_build_embedding_inputs_no_heading_path_is_passthrough() -> None:
    item = SimpleNamespace(
        content="chunk",
        metadata=None,
        chunk_role="default",
        parent_ref=None,
    )
    assert build_embedding_inputs(
        chunk_items=[item], contexts=None, contextual_enabled=False
    ) == ["chunk"]


def test_build_embedding_inputs_parent_child_prefix_and_context() -> None:
    parent = SimpleNamespace(
        content="P",
        metadata=None,
        chunk_role="parent",
        parent_ref=None,
    )
    child = SimpleNamespace(
        content="C",
        metadata={"heading_path": "H"},
        chunk_role="child",
        parent_ref=0,
    )
    assert build_embedding_inputs(
        chunk_items=[parent, child],
        contexts=["", "CTX"],
        contextual_enabled=True,
    ) == ["P", "H : P\n\nC\n\nCTX"]

