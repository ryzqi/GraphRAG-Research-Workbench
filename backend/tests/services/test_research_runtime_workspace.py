"""research_runtime_workspace 按预算注入文件并记录 snapshot。"""

from app.services.research_runtime_types import ResearchWorkspaceBudget
from app.services.research_runtime_workspace import (
    build_runtime_request_files_with_budget,
)


def _big(text: str, chars: int) -> str:
    return text * (chars // max(len(text), 1))


def test_budget_spills_low_priority_when_budget_exceeded() -> None:
    files = {
        "/workspace/research/s/04-claim-map.json": _big("x", 4000),
        "/workspace/research/s/05-evidence-ledger.json": _big("y", 4000),
        "/workspace/research/s/03-report-outline.md": _big("z", 20000),
        "/workspace/research/s/09-live-board.json": _big("q", 20000),
    }
    priority_paths = (
        "/workspace/research/s/04-claim-map.json",
        "/workspace/research/s/05-evidence-ledger.json",
    )
    budget = ResearchWorkspaceBudget(total_tokens_budget=4000, priority_reserve=3000)
    request_files, snapshot = build_runtime_request_files_with_budget(
        files=files,
        priority_paths=priority_paths,
        budget=budget,
    )
    assert "/workspace/research/s/04-claim-map.json" in request_files
    assert "/workspace/research/s/05-evidence-ledger.json" in request_files
    assert snapshot["spilled_paths"]
    assert "/workspace/research/s/09-live-board.json" in snapshot["spilled_paths"]
