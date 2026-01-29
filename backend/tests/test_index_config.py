from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig


def test_index_config_parent_child_allows_contextual_enabled_true() -> None:
    # Regression test: we must NOT silently force contextual.enabled=false under parent_child.
    cfg = IndexConfig.model_validate(
        {
            "chunking": {"general_strategy": ChunkingStrategy.PARENT_CHILD},
            "contextual": {"enabled": True},
        }
    )
    assert cfg.chunking.general_strategy == ChunkingStrategy.PARENT_CHILD
    assert cfg.contextual.enabled is True


def test_index_config_markdown_heading_compat_legacy_fields() -> None:
    # Compatibility: old data used markdown_heading.enabled + max_section_chars.
    cfg = IndexConfig.model_validate(
        {
            "chunking": {
                "markdown_heading": {
                    "enabled": True,
                    "max_heading_level": 3,
                    "max_section_chars": 1234,
                },
            }
        }
    )
    assert cfg.chunking.markdown_heading.chunk_size == 1234
