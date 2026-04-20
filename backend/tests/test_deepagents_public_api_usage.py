from pathlib import Path


def test_research_runtime_factory_does_not_depend_on_deepagents_internal_graph_api() -> None:
    source = Path("src/app/services/research_runtime_factory.py").read_text(
        encoding="utf-8"
    )

    assert "from deepagents import create_deep_agent" in source
    assert "deepagents.graph" not in source
    assert "remove_deepagents_anthropic_prompt_caching" not in source


def test_backend_sources_do_not_reference_deepagents_internal_graph_module() -> None:
    python_sources = Path("src/app").rglob("*.py")

    offending = [
        str(path)
        for path in python_sources
        if "deepagents.graph" in path.read_text(encoding="utf-8")
    ]

    assert offending == []
