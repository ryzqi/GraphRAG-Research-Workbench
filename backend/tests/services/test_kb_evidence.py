from __future__ import annotations

from app.services.kb_evidence import resolve_structured_evidence


def test_resolve_structured_evidence_reindexes_and_rebuilds_context() -> None:
    evidence_items, citation_catalog, context = resolve_structured_evidence(
        [
            {
                "citation_id": "s9",
                "chunk_id": "chunk-1",
                "material_id": "material-1",
                "kb_id": "kb-1",
                "excerpt": "第一条证据。",
            },
            {
                "citation_id": "S1",
                "chunk_id": "chunk-2",
                "material_id": "material-2",
                "kb_id": "kb-1",
                "excerpt": "第二条证据。",
            },
        ],
        citation_catalog={
            "s9": {"citation_id": "s9", "citation_title": "资料9"},
            "S1": {"citation_id": "S1", "citation_title": "资料1"},
        },
        reindex=True,
    )

    assert [item["citation_id"] for item in evidence_items] == ["S1", "S2"]
    assert sorted(citation_catalog) == ["S1", "S2"]
    assert context == "[S1] 第一条证据。\n\n[S2] 第二条证据。"
