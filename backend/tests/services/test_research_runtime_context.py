"""runtime_context snapshot 对齐新 layout。"""

import json
from uuid import uuid4

from app.services.research_runtime_context import build_runtime_context_snapshot
from app.services.research_workspace_files import build_research_workspace_layout


def test_snapshot_captures_claim_map_and_ledger_json() -> None:
    layout = build_research_workspace_layout(uuid4())
    files = {
        layout.claim_map_json_path: json.dumps(
            {"claims": [], "generated_at": "2026-04-19T00:00:00Z"}
        ),
        layout.evidence_ledger_json_path: json.dumps(
            {"evidences": [], "generated_at": "2026-04-19T00:00:00Z"}
        ),
        layout.evidence_critique_json_path: json.dumps({"claims": []}),
        layout.coverage_critique_json_path: json.dumps({"orphan_citations": []}),
    }
    result = {
        "files": {
            path: {"content": content, "encoding": "utf-8"}
            for path, content in files.items()
        }
    }
    snapshot = build_runtime_context_snapshot(result=result, layout=layout)
    assert snapshot is not None
    assert snapshot.claim_map_json == {
        "claims": [],
        "generated_at": "2026-04-19T00:00:00Z",
    }
    assert snapshot.evidence_ledger_json == {
        "evidences": [],
        "generated_at": "2026-04-19T00:00:00Z",
    }
    assert snapshot.evidence_critique_json == {"claims": []}
    assert snapshot.coverage_critique_json == {"orphan_citations": []}
