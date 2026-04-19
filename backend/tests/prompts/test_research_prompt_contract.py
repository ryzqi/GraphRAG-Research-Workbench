"""shared_contract 与主 / subagent 提示词加载检查。"""

from app.prompts import get_prompt_loader


def test_shared_contract_template_exists() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/shared_contract")
    assert "证据硬约束" in template.template
    assert "反证硬约束" in template.template
    assert "≥ 2" in template.template or "两" in template.template


def test_shared_contract_has_no_required_variables() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/shared_contract")
    assert template.variables == []
