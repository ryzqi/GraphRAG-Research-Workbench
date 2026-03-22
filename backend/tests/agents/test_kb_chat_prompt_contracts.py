from __future__ import annotations

from app.prompts import get_prompt_loader


def _render_prompt(key: str) -> str:
    loader = get_prompt_loader()
    loader.reload()
    return loader.render_with_few_shot(key)


def test_kb_chat_system_prompt_requires_full_coverage_for_multi_part_mapping_questions() -> None:
    rendered = _render_prompt("kb_chat/system")

    assert "若问题同时要求多个必答子项，必须逐一覆盖" in rendered
    assert "组件 -> 作用 -> 所支撑差异" in rendered


def test_kb_chat_answer_review_prompt_marks_missing_required_mapping_as_incomplete() -> None:
    rendered = _render_prompt("kb_chat/answer_review")

    assert "缺任一必答子项都应判为 `incomplete`" in rendered
    assert "机制/组件 -> 作用 -> 所支撑的结论/差异/结果" in rendered
