from __future__ import annotations

import json
from string import Formatter

import pytest

from app.prompts import get_prompt_loader


DUMMY_VALUES_BY_TYPE = {
    "string": "示例文本",
    "number": 3,
    "integer": 3,
    "boolean": True,
}


STRUCTURED_PROMPT_FIELDS: dict[str, tuple[str, ...]] = {
    "kb_chat/resolve_reference": (
        "json",
        "resolved_query",
        "triggered",
        "confidence",
        "selected_mention",
        "needs_clarification",
        "reasoning",
    ),
    "kb_chat/ambiguity_decision": (
        "json",
        "ambiguous",
        "reason_code",
        "confidence",
        "clarifying_question",
        "missing_slots",
        "suggested_answers",
    ),
    "kb_chat/transform_query": ("json", "query"),
    "kb_chat/normalize_query": (
        "json",
        "canonical_query",
        "aliases",
        "entities",
        "time_constraints",
        "metric_constraints",
        "scope_constraints",
        "recall_risk",
        "drift_risk",
        "reasoning",
    ),
    "kb_chat/context_merge": (
        "json",
        "summary_text",
        "keep_memory",
        "notes",
    ),
    "kb_chat/complexity_classify": (
        "json",
        "reasoning",
        "strategy",
        "confidence",
        "risk_flags",
        "decision_version",
    ),
    "kb_chat/decomposition": (
        "json",
        "strategy",
        "plan_version",
        "sub_queries",
        "sub_query_specs",
        "risk_flags",
        "reasoning",
    ),
    "kb_chat/multi_query": ("json", "queries"),
    "kb_chat/entity_expand": (
        "json",
        "candidates",
        "dropped_queries",
        "reasoning",
        "query",
        "confidence",
    ),
    "kb_chat/hyde": ("json", "hypothetical_documents"),
    "kb_chat/answer_review": (
        "json",
        "passed",
        "reason",
        "confidence",
        "missing_citations",
        "unsupported_claims",
    ),
    "kb_chat/citation_review": (
        "json",
        "passed",
        "reason",
        "confidence",
        "missing_citations",
        "unsupported_claims",
    ),
    "tools/report_generate": (
        "json",
        "report_md",
        "sections",
        "metadata",
        "confidence_level",
        "evidence_count",
        "has_conflicts",
        "generated_at",
    ),
    "tools/research_plan": (
        "json",
        "original_question",
        "complexity",
        "research_type",
        "subtasks",
        "estimated_steps",
        "suggested_approach",
        "key_assumptions",
        "success_criteria",
    ),
}


@pytest.fixture(scope="module")
def prompt_loader():
    return get_prompt_loader()


@pytest.mark.parametrize("key", sorted(STRUCTURED_PROMPT_FIELDS))
def test_structured_prompts_document_output_contracts(prompt_loader, key: str) -> None:
    template = prompt_loader.get(key).template.lower()
    for token in STRUCTURED_PROMPT_FIELDS[key]:
        assert token.lower() in template


def test_all_prompt_templates_have_renderable_variable_contracts(prompt_loader) -> None:
    formatter = Formatter()

    for key, template in prompt_loader._templates.items():
        placeholders = {
            field_name
            for _, field_name, _, _ in formatter.parse(template.template)
            if field_name
        }
        declared = [item["name"] for item in template.variables]
        assert len(declared) == len(set(declared)), key
        assert placeholders == set(declared), key

        kwargs = {
            item["name"]: DUMMY_VALUES_BY_TYPE[item["type"]]
            for item in template.variables
        }
        rendered = prompt_loader.render(key, **kwargs)
        assert isinstance(rendered, str)
        if template.few_shot_examples:
            rendered_with_examples = prompt_loader.render_with_few_shot(key, **kwargs)
            assert "示例输入" in rendered_with_examples
            assert "示例输出" in rendered_with_examples


def test_complexity_classify_prompt_includes_diverse_route_examples_and_v5_contract(
    prompt_loader,
) -> None:
    template = prompt_loader.get("kb_chat/complexity_classify")
    assert "kb_chat_complexity_classify_v5" in template.template
    assert template.few_shot_examples, "complexity_classify should use few-shot examples"

    strategies = {
        json.loads(str(example["output"]))["strategy"] for example in template.few_shot_examples
    }
    assert {"direct", "multi_query", "decomposition"}.issubset(strategies)


def test_report_generate_prompt_matches_runtime_confidence_levels(prompt_loader) -> None:
    template = prompt_loader.get("tools/report_generate").template.lower()
    assert "sufficient" in template
    assert "high" not in template


def test_general_and_kb_system_prompts_keep_core_operating_rules(prompt_loader) -> None:
    general_prompt = prompt_loader.get("general_chat/system").template.lower()
    kb_prompt = prompt_loader.get("kb_chat/system").template.lower()
    research_prompt = prompt_loader.get("research/deep_agent_system").template.lower()

    assert "get_system_time" in general_prompt
    assert "yyyy-mm-dd" in general_prompt

    assert "[s1]" in kb_prompt
    assert "只能基于" in prompt_loader.get("kb_chat/system").template
    assert "引用" in prompt_loader.get("kb_chat/system").template

    assert "kb_retrieve" in research_prompt
    assert "report_generate" in research_prompt

