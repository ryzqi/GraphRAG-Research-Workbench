from __future__ import annotations

from app.prompts import get_prompt_loader


def _render_prompt(key: str, **kwargs: object) -> str:
    loader = get_prompt_loader()
    loader.reload()
    return loader.render_with_few_shot(key, **kwargs)


def test_general_chat_system_prompt_requires_web_search_for_latest_or_current_facts() -> None:
    rendered = _render_prompt("general_chat/system")

    assert "最新" in rendered
    assert "web_search" in rendered
    assert "必须先调用 web_search" in rendered


def test_general_chat_system_prompt_requires_web_extract_when_search_snippets_are_insufficient() -> None:
    rendered = _render_prompt("general_chat/system")

    assert "web_extract" in rendered
    assert "搜索结果摘要不足" in rendered
    assert "基于片段猜测" in rendered
