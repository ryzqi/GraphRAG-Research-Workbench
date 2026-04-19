"""已废弃的 markdown / query_mesh 模板不得再加载。"""

import pytest

from app.prompts.loader import get_prompt_loader


@pytest.fixture(autouse=True)
def _reset_prompt_loader() -> None:
    get_prompt_loader.cache_clear()
    loader = get_prompt_loader()
    loader.reload()


@pytest.mark.parametrize(
    "key",
    [
        "research/claim_map_md",
        "research/evidence_ledger_md",
        "research/analysis_notes_md",
        "research/coverage_md",
        "research/query_map_md",
        "research/query_mesh_breadth_compare",
        "research/query_mesh_depth_fallback",
        "research/query_mesh_depth_subtask_evidence",
        "research/query_mesh_subtask_verification",
        "research/query_mesh_verification_crosscheck",
        "research/query_mesh_verification_risks",
    ],
)
def test_legacy_template_removed(key: str) -> None:
    loader = get_prompt_loader()
    with pytest.raises(KeyError):
        loader.get(key)
