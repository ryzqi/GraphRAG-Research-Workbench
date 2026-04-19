"""runtime_user 去除先写大纲再搜证据的约束。"""

from app.prompts import get_prompt_loader


def test_runtime_user_does_not_require_outline_before_search() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/runtime_user").template
    assert "先创建动态全文大纲" not in template
    assert "先写好 `report-outline`" not in template


def test_runtime_user_references_pipeline_phases() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/runtime_user").template
    assert "breadth-pass" in template
    assert "claim-map.json" in template
    assert "evidence-ledger.json" in template
