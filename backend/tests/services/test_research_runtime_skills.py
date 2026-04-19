"""research_runtime_skills 内容对齐新 pipeline。"""

from app.services.research_runtime_skills import build_research_runtime_skill_files


def test_skill_files_include_runtime_and_critic_workflow() -> None:
    files = build_research_runtime_skill_files()
    assert "/skills/research-runtime/SKILL.md" in files
    assert "/skills/research-reporting/SKILL.md" in files
    runtime = files["/skills/research-runtime/SKILL.md"]
    for keyword in (
        "breadth-pass",
        "depth-pass",
        "critic-pass",
        "evidence-critic",
        "coverage-critic",
        "claim-map.json",
        "evidence-ledger.json",
    ):
        assert keyword in runtime, f"SKILL.md 缺少 {keyword}"


def test_skill_files_drop_legacy_outline_first_instruction() -> None:
    files = build_research_runtime_skill_files()
    runtime = files["/skills/research-runtime/SKILL.md"]
    assert "先创建动态全文大纲" not in runtime
