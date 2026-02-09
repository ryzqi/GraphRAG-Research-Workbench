from __future__ import annotations

import string

import pytest

from app.prompts import PromptLoader

REQUIRED_KEYS = {
    "general_chat/system",
    "ingestion/contextual_embedding",
    "kb_chat/answer_check",
    "kb_chat/doc_grader",
    "kb_chat/hallucination_check",
    "kb_chat/reverse_question",
    "kb_chat/system",
    "kb_chat/transform_query",
    "research/deep_agent_system",
    "retrieval/query_rewrite",
    "tools/evidence_compare",
    "tools/report_generate",
    "tools/research_plan",
}

REMOVED_KEYS = {
    "general_chat/tool_selection",
    "kb_chat/decomposition",
    "kb_chat/hyde",
    "kb_chat/multi_query",
}


@pytest.fixture()
def loader() -> PromptLoader:
    prompt_loader = PromptLoader()
    prompt_loader.reload()
    return prompt_loader


def _extract_placeholders(template: str) -> set[str]:
    fields: set[str] = set()
    formatter = string.Formatter()
    for _, field_name, _, _ in formatter.parse(template):
        if not field_name:
            continue
        normalized = field_name.split(".", 1)[0].split("[", 1)[0]
        if normalized:
            fields.add(normalized)
    return fields


def _sample_value(var_type: str) -> int | str:
    lower = (var_type or "").lower()
    if lower in {"number", "integer", "int", "float"}:
        return 2
    return "示例值"


def test_required_prompt_keys_exist(loader: PromptLoader) -> None:
    keys = set(loader._templates.keys())
    assert REQUIRED_KEYS.issubset(keys)


def test_removed_prompt_keys_are_absent(loader: PromptLoader) -> None:
    for key in REMOVED_KEYS:
        with pytest.raises(KeyError):
            loader.get(key)


def test_declared_variables_match_template_placeholders(loader: PromptLoader) -> None:
    for key, prompt in loader._templates.items():
        declared = {
            str(item.get("name"))
            for item in prompt.variables
            if isinstance(item, dict) and item.get("name")
        }
        placeholders = _extract_placeholders(prompt.template)
        assert placeholders == declared, key


def test_all_templates_render_with_declared_variables(loader: PromptLoader) -> None:
    for key, prompt in loader._templates.items():
        kwargs = {
            str(item.get("name")): _sample_value(str(item.get("type", "string")))
            for item in prompt.variables
            if isinstance(item, dict) and item.get("name")
        }
        rendered = loader.render(key, **kwargs)
        assert isinstance(rendered, str)
        assert rendered.strip(), key
