from __future__ import annotations

from app.prompts import get_prompt_loader


def _render_prompt(key: str, **kwargs: object) -> str:
    loader = get_prompt_loader()
    loader.reload()
    return loader.render_with_few_shot(key, **kwargs)


def test_kb_chat_system_prompt_requires_full_coverage_for_multi_part_mapping_questions() -> None:
    rendered = _render_prompt("kb_chat/system")

    assert "若问题同时要求多个必答子项，必须逐一覆盖" in rendered
    assert "组件 -> 作用 -> 所支撑差异" in rendered


def test_kb_chat_answer_review_prompt_marks_missing_required_mapping_as_incomplete() -> None:
    rendered = _render_prompt("kb_chat/answer_review")

    assert "缺任一必答子项都应判为 `incomplete`" in rendered
    assert "机制/组件 -> 作用 -> 所支撑的结论/差异/结果" in rendered


def test_kb_chat_system_prompt_requires_explicit_retention_of_required_technical_names() -> None:
    rendered = _render_prompt("kb_chat/system")

    assert "若问题要求技术架构、模型名称、组件名称、职责标签、阶段名或术语清单" in rendered
    assert "必须显式保留参考内容中的原始名词" in rendered
    assert "不能只用机制描述替代原始名词" in rendered


def test_kb_chat_answer_review_prompt_marks_missing_required_technical_names_as_incomplete() -> None:
    rendered = _render_prompt("kb_chat/answer_review")

    assert "若问题要求技术架构、模型名称、组件名称、职责标签、阶段名或术语清单" in rendered
    assert "只描述机制但未显式保留参考内容中的原始名词" in rendered
    assert "仍属于 `incomplete`" in rendered


def test_kb_chat_system_prompt_forbids_generalizing_entity_specific_attributes() -> None:
    rendered = _render_prompt("kb_chat/system")

    assert "多实体并列问题" in rendered
    assert "不得把只属于某一实体的属性泛化成所有实体的共同结论" in rendered


def test_kb_chat_answer_review_prompt_marks_entity_specific_attribute_merge_as_failure() -> None:
    rendered = _render_prompt("kb_chat/answer_review")

    assert "只属于某一实体的技术架构、挑战或职责错误泛化到全部实体" in rendered
    assert "属于 `unsupported_claims` 或 `incomplete`" in rendered


def test_kb_chat_context_compress_prompt_requires_multi_entity_dimension_coverage_or_keep_all() -> None:
    rendered = _render_prompt("kb_chat/context_compress")

    assert "若问题同时要求多个实体与多个必答维度" in rendered
    assert "必须保留每个实体 × 每个必答维度至少一条原文证据" in rendered
    assert "若无法完整覆盖，直接输出 decision=keep_all" in rendered


def test_kb_chat_complexity_classify_prompt_includes_guardrails_for_stable_overview_and_multi_target_questions() -> None:
    rendered = _render_prompt(
        "kb_chat/complexity_classify",
        question="AI Agent 的六大核心组件是什么？",
        recall_risk="medium",
        has_multi_target=False,
        is_comparison=False,
    )

    assert "不要仅因标准专有名词中英混写就判为 multi_query" in rendered
    assert "AI Agent 的六大核心组件是什么？" in rendered
    assert "Embedding 模型和 Re-rank 模型分别负责什么、采用什么技术架构、各自面临哪些挑战？" in rendered
    assert "出现“分别”“各自”等并列回答多个实体/子问题的信号时，应优先判为 decomposition" in rendered


def test_kb_chat_multi_query_prompt_preserves_taxonomy_questions() -> None:
    rendered = _render_prompt(
        "kb_chat/multi_query",
        question="Chain-of-Thought（CoT，思维链）的主要变体有哪些？",
    )

    assert "当用户问题本身在问“主要变体 / 类型 / 分类 / 列表 / 有哪些”时" in rendered
    assert "不要把这类问题改写成应用场景、性能对比或优缺点问题" in rendered
