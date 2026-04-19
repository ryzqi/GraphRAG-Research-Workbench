"""runtime_system 新版断言。"""

from app.prompts import get_prompt_loader


def test_runtime_system_has_pipeline_section() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/runtime_system").template
    for keyword in (
        "breadth-pass",
        "depth-pass",
        "critic-pass",
        "finalize-pass",
        "evidence-critic",
        "coverage-critic",
    ):
        assert keyword in template, f"runtime_system 缺少 {keyword}"


def test_runtime_system_has_hard_no_block() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/runtime_system").template
    assert "<hard_no>" in template
    assert "`??`" in template or "默认值" in template


def test_runtime_system_requires_shared_contract_variable() -> None:
    loader = get_prompt_loader()
    template = loader.get("research/runtime_system")
    names = {item["name"] for item in template.variables}
    assert "shared_contract_block" in names
