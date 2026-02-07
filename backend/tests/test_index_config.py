import uuid

import pytest
from pydantic import ValidationError

from app.schemas.knowledge_bases import ChunkingStrategy, IndexConfig, KnowledgeBaseRead


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


def test_index_config_retrieval_parent_child_rejects_legacy_enabled_field() -> None:
    with pytest.raises(ValidationError):
        IndexConfig.model_validate(
            {
                "retrieval": {
                    "parent_child": {
                        "enabled": True,
                    }
                }
            }
        )


def test_knowledge_base_read_rejects_legacy_retrieval_parent_child_enabled_field() -> None:
    with pytest.raises(ValidationError):
        KnowledgeBaseRead.model_validate(
            {
                "id": str(uuid.uuid4()),
                "name": "kb",
                "description": None,
                "tags": None,
                "status": "active",
                "index_config": {
                    "retrieval": {
                        "parent_child": {
                            "enabled": False,
                            "max_parents": 5,
                            "max_children_per_parent": 2,
                        }
                    }
                },
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        )
