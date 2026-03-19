from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace

import pytest


def _load_query_policy_module():
    spec = importlib.util.find_spec("app.services.kb_query_policy")
    assert spec is not None, "app.services.kb_query_policy should exist"
    return importlib.import_module("app.services.kb_query_policy")


def _load_query_planner_module():
    spec = importlib.util.find_spec("app.services.kb_query_planner_service")
    assert spec is not None, "app.services.kb_query_planner_service should exist"
    return importlib.import_module("app.services.kb_query_planner_service")


def _settings(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "app_env": "test",
        "kb_chat_json_safe_policy": "stringify",
        "kb_chat_query_planner_enabled": True,
        "kb_chat_query_planner_max_first_pass_items": 3,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_query_planner_rejects_fragment_only_candidates() -> None:
    module = _load_query_policy_module()
    build_validated_query_items = getattr(module, "build_validated_query_items", None)
    assert callable(build_validated_query_items), (
        "build_validated_query_items should exist in app.services.kb_query_policy"
    )

    result = build_validated_query_items(
        normalized_query="解释agent的记忆系统",
        planned_items=[
            {"kind": "main", "query": "解释agent的记忆系统"},
            {"kind": "paraphrase", "query": "agent"},
            {"kind": "paraphrase", "query": "的记忆系统"},
        ],
    )

    assert [item["query"] for item in result.items] == ["解释agent的记忆系统"]
    assert result.rejections["fragment_rejected"] == 2


def test_query_planner_keeps_complete_mixed_language_paraphrase() -> None:
    module = _load_query_policy_module()
    build_validated_query_items = getattr(module, "build_validated_query_items", None)
    assert callable(build_validated_query_items), (
        "build_validated_query_items should exist in app.services.kb_query_policy"
    )

    result = build_validated_query_items(
        normalized_query="解释agent的记忆系统",
        planned_items=[
            {"kind": "main", "query": "解释agent的记忆系统"},
            {"kind": "paraphrase", "query": "智能体记忆系统"},
        ],
    )

    assert [item["query"] for item in result.items] == [
        "解释agent的记忆系统",
        "智能体记忆系统",
    ]


def test_is_semantically_complete_rejects_orphaned_phrases() -> None:
    module = _load_query_policy_module()
    is_semantically_complete = getattr(module, "is_semantically_complete", None)
    assert callable(is_semantically_complete), (
        "is_semantically_complete should exist in app.services.kb_query_policy"
    )

    assert is_semantically_complete("agent") is False
    assert is_semantically_complete("的记忆系统") is False
    assert is_semantically_complete("智能体记忆系统") is True


def test_should_enable_hyde_only_for_allowed_conditions() -> None:
    module = _load_query_policy_module()
    should_enable_hyde = getattr(module, "should_enable_hyde", None)
    assert callable(should_enable_hyde), (
        "should_enable_hyde should exist in app.services.kb_query_policy"
    )

    assert (
        should_enable_hyde(
            strategy="direct",
            recall_risk="low",
            first_pass_failed=False,
        )
        is False
    )
    assert (
        should_enable_hyde(
            strategy="direct",
            recall_risk="high",
            first_pass_failed=True,
        )
        is True
    )


@pytest.mark.asyncio
async def test_query_planner_normalizes_prompt_output_into_query_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_query_planner_module()
    planner_cls = getattr(module, "KbQueryPlannerService", None)
    assert planner_cls is not None, (
        "KbQueryPlannerService should exist in app.services.kb_query_planner_service"
    )

    async def _fake_call_planner_prompt(self, *, normalized_query: str, normalized_meta: dict[str, object]):
        _ = self, normalized_query, normalized_meta
        return {
            "strategy": "paraphrase",
            "reasoning": "中英混合术语需要补充同义表达",
            "items": [
                {
                    "kind": "paraphrase",
                    "query": "智能体记忆系统",
                    "strategy_source": "planner_llm",
                    "trigger_reason": "mixed_language_paraphrase",
                    "retrieval_mode": "hybrid",
                    "priority": 2,
                    "purpose": "补充中文术语表达",
                },
                {
                    "kind": "paraphrase",
                    "query": "agent",
                    "strategy_source": "planner_llm",
                    "trigger_reason": "bad_fragment",
                    "retrieval_mode": "hybrid",
                    "priority": 3,
                    "purpose": "这个片段应被拒绝",
                },
            ],
        }

    monkeypatch.setattr(planner_cls, "_call_planner_prompt", _fake_call_planner_prompt)

    planner = planner_cls(settings=_settings())
    result = await planner.plan(
        normalized_query="解释agent的记忆系统",
        normalized_meta={"recall_risk": "high", "aliases": ["智能体"]},
    )

    assert result.strategy in {"direct", "paraphrase", "decomposition"}
    assert [item["query"] for item in result.items] == [
        "解释agent的记忆系统",
        "智能体记忆系统",
    ]
    assert result.items[0]["kind"] == "main"
    assert all(item["semantic_complete"] is True for item in result.items)
    assert result.diagnostics["rejection_counts"]["fragment_rejected"] == 1


@pytest.mark.asyncio
async def test_query_planner_fail_opens_to_canonical_query_when_prompt_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_query_planner_module()
    planner_cls = getattr(module, "KbQueryPlannerService", None)
    assert planner_cls is not None, (
        "KbQueryPlannerService should exist in app.services.kb_query_planner_service"
    )

    async def _fake_call_planner_prompt(self, *, normalized_query: str, normalized_meta: dict[str, object]):
        _ = self, normalized_query, normalized_meta
        raise RuntimeError("planner unavailable")

    monkeypatch.setattr(planner_cls, "_call_planner_prompt", _fake_call_planner_prompt)

    planner = planner_cls(settings=_settings())
    result = await planner.plan(
        normalized_query="解释agent的记忆系统",
        normalized_meta={"recall_risk": "high"},
    )

    assert result.strategy == "direct"
    assert [item["query"] for item in result.items] == ["解释agent的记忆系统"]
    assert result.diagnostics["fallback_reason"] == "prompt_failed"
