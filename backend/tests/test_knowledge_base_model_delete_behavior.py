from __future__ import annotations

from app.models.knowledge_base import KnowledgeBase


def test_knowledge_base_delete_relations_use_passive_deletes_all() -> None:
    relation_names = (
        "materials",
        "chunks",
        "ingestion_batches",
        "config_snapshots",
        "index_rebuild_jobs",
    )

    for relation_name in relation_names:
        relation = getattr(KnowledgeBase, relation_name).property
        assert relation.passive_deletes == "all"
