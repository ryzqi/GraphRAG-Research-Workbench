"""research_runtime_factory：新 subagent 集合，无 general-purpose。"""

from app.prompts import get_prompt_loader
from app.services.research_runtime_factory import _assemble_research_subagents
from app.services.research_runtime_types import ResearchRuntimeConfig


class _FakeModel:
    name = "fake"


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _build_config() -> ResearchRuntimeConfig:
    loader = get_prompt_loader()
    shared = loader.render("research/shared_contract")
    system_prompt = loader.render(
        "research/runtime_system",
        shared_contract_block=shared,
    )
    return ResearchRuntimeConfig(
        primary_model=_FakeModel(),
        subagent_model=_FakeModel(),
        finalizer_model=_FakeModel(),
        system_prompt=system_prompt,
    )


def _tools() -> list[_FakeTool]:
    return [
        _FakeTool("web_search"),
        _FakeTool("jina_read"),
        _FakeTool("tavily_extract"),
        _FakeTool("tavily_crawl"),
        _FakeTool("arxiv_search"),
        _FakeTool("arxiv_fetch"),
        _FakeTool("record_runtime_activity"),
    ]


def test_subagents_contain_only_expected_names() -> None:
    config = _build_config()
    subagents = _assemble_research_subagents(
        config=config,
        tools=_tools(),
        tool_groups={
            "web": ("web_search", "jina_read", "tavily_extract", "tavily_crawl"),
            "paper": ("arxiv_search", "arxiv_fetch"),
            "web_provider_ids": ("tavily", "searxng", "jina_reader"),
            "citation": (),
        },
        resolved_skill_paths=["/skills/research-runtime/"],
    )
    names = {subagent["name"] for subagent in subagents}
    assert names == {
        "web-researcher",
        "paper-researcher",
        "claim-verifier",
        "section-writer",
        "citation-steward",
        "evidence-critic",
        "coverage-critic",
    }
    assert "general-purpose" not in names


def test_section_writer_has_no_search_tools() -> None:
    config = _build_config()
    subagents = _assemble_research_subagents(
        config=config,
        tools=_tools(),
        tool_groups={
            "web": ("web_search", "jina_read", "tavily_extract", "tavily_crawl"),
            "paper": ("arxiv_search", "arxiv_fetch"),
            "web_provider_ids": (),
            "citation": (),
        },
        resolved_skill_paths=[],
    )
    section_writer = next(
        subagent for subagent in subagents if subagent["name"] == "section-writer"
    )
    tool_names = {tool.name for tool in section_writer.get("tools", [])}
    assert "web_search" not in tool_names
    assert "arxiv_search" not in tool_names
    assert "record_runtime_activity" in tool_names


def test_critics_are_readonly_without_tools() -> None:
    config = _build_config()
    subagents = _assemble_research_subagents(
        config=config,
        tools=_tools(),
        tool_groups={
            "web": ("web_search",),
            "paper": ("arxiv_search",),
            "web_provider_ids": (),
            "citation": (),
        },
        resolved_skill_paths=[],
    )
    for critic_name in ("evidence-critic", "coverage-critic"):
        critic = next(
            subagent for subagent in subagents if subagent["name"] == critic_name
        )
        assert "tools" not in critic or not critic["tools"]
