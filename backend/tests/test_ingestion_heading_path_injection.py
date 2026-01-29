from app.worker.tasks.ingestion import _build_embedding_input_text


def test_build_embedding_input_text_injects_heading_path_prefix() -> None:
    # Used by markdown_heading strategy chunks which emit metadata.heading_path.
    assert (
        _build_embedding_input_text(chunk_text="chunk", heading_path="A > B")
        == "A > B : chunk"
    )


def test_build_embedding_input_text_no_heading_path_is_passthrough() -> None:
    assert _build_embedding_input_text(chunk_text="chunk", heading_path=None) == "chunk"

