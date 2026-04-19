"""researcher subagent 模板加载。"""

import pytest

from app.prompts import get_prompt_loader


@pytest.mark.parametrize(
    ("key", "keyword"),
    [
        ("research/subagent_web", "web-researcher"),
        ("research/subagent_paper", "paper-researcher"),
        ("research/subagent_claim_verifier", "claim-verifier"),
        ("research/subagent_section_writer", "section-writer"),
        ("research/subagent_citation_steward", "citation-steward"),
    ],
)
def test_researcher_subagent_template_exists(key: str, keyword: str) -> None:
    loader = get_prompt_loader()
    template = loader.get(key).template
    assert keyword in template
    assert "{shared_contract_block}" in template
    assert "<handoff>" in template
    assert "<output>" in template
