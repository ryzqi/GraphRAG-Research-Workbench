"""critic subagent 模板加载。"""

from app.prompts import get_prompt_loader


def test_evidence_critic_template_structure() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/subagent_evidence_critic").template
    assert "evidence-critic" in template
    assert "evidence-critique.json" in template
    assert "verdict_rollup" in template


def test_coverage_critic_template_structure() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/subagent_coverage_critic").template
    assert "coverage-critic" in template
    assert "coverage-critique.json" in template
    assert "orphan_citations" in template
    assert "counter_search_status" in template
