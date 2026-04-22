from __future__ import annotations

from app.services.research_runtime_workspace_backend import _canonicalize_runtime_path
from app.services.research_workspace_files import build_research_workspace_layout


def test_canonicalize_runtime_path_maps_legacy_workspace_aliases(
    monkeypatch,
) -> None:
    session_id = "session-123"
    layout = build_research_workspace_layout(session_id)

    monkeypatch.setattr(
        "app.services.research_runtime_workspace_backend._runtime_session_id",
        lambda: session_id,
    )

    assert _canonicalize_runtime_path("/evidence-ledger.json") == layout.evidence_ledger_json_path
    assert _canonicalize_runtime_path("claim-map.json") == layout.claim_map_json_path
    assert _canonicalize_runtime_path(
        f"{layout.workspace_root}/claim-bundles.json"
    ) == layout.claim_bundles_path
    assert _canonicalize_runtime_path("/coverage-critique.json") == layout.coverage_critique_json_path
    assert _canonicalize_runtime_path(
        f"{layout.workspace_root}/04-claim_map.json"
    ) == layout.claim_map_json_path
    assert _canonicalize_runtime_path(
        "/workspace/research/<session>/05-evidence-ledger.json"
    ) == layout.evidence_ledger_json_path
    assert _canonicalize_runtime_path(
        "/scratch/research/<session>/critique/coverage_critique.json"
    ) == layout.coverage_critique_json_path
    assert _canonicalize_runtime_path(
        "/scratch/research/<session>/evidence-critique.json"
    ) == layout.evidence_critique_json_path
    assert _canonicalize_runtime_path(
        f"{layout.scratch_root}/coverage-critique.json"
    ) == layout.coverage_critique_json_path


def test_canonicalize_runtime_path_keeps_unknown_paths(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.research_runtime_workspace_backend._runtime_session_id",
        lambda: "session-123",
    )

    assert _canonicalize_runtime_path("/workspace/research/session-123/custom.json") == (
        "/workspace/research/session-123/custom.json"
    )
    assert _canonicalize_runtime_path("/workspace/research/<session>/custom.json") == (
        "/workspace/research/session-123/custom.json"
    )
