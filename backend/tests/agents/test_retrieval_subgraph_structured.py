from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.retrieval_subgraph import _compress_context
from app.services.kb_evidence import build_citation_catalog, build_evidence_context


def _evidence_items() -> list[dict[str, object]]:
    return [
        {
            "citation_id": "S1",
            "excerpt": "接口默认超时时间为 30 秒，可通过 timeout 参数覆盖。",
            "material_title": "超时配置",
        },
        {
            "citation_id": "S2",
            "excerpt": "系统支持重试与熔断策略。",
            "material_title": "稳定性配置",
        },
    ]


class _FakeStructuredModel:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result

    async def ainvoke(self, request: object) -> dict[str, object]:
        assert request
        return self._result


class _FakeChatModel:
    def __init__(self, result: dict[str, object]) -> None:
        self._result = result
        self.calls: list[tuple[object, bool]] = []

    def with_structured_output(
        self,
        schema: object,
        *,
        include_raw: bool = False,
    ) -> _FakeStructuredModel:
        self.calls.append((schema, include_raw))
        return _FakeStructuredModel(self._result)


@pytest.mark.asyncio
async def test_context_compress_prefers_structured_subset_output() -> None:
    evidence_items = _evidence_items()
    state = {
        "normalized_query": "系统默认超时时间是多少",
        "final_context": build_evidence_context(evidence_items),
        "evidence_items": evidence_items,
        "citation_catalog": build_citation_catalog(evidence_items),
        "stage_summaries": {},
    }
    chat_model = _FakeChatModel(
        {
            "parsed": {
                "decision": "subset",
                "items": [
                    {
                        "citation_id": "S1",
                        "excerpt": "接口默认超时时间为 30 秒，可通过 timeout 参数覆盖。",
                    }
                ],
            },
            "parsing_error": None,
        }
    )

    result = await _compress_context(
        state,
        runtime=SimpleNamespace(),
        settings=SimpleNamespace(),
        chat_model=chat_model,
    )

    assert chat_model.calls, "应通过 with_structured_output 走结构化主路径"
    assert result["final_context"] == "[S1] 接口默认超时时间为 30 秒，可通过 timeout 参数覆盖。"
    assert result["compression_stats"]["fallback_used"] is False
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1"]


@pytest.mark.asyncio
async def test_context_compress_falls_back_on_invalid_structured_citation() -> None:
    evidence_items = _evidence_items()
    original_context = build_evidence_context(evidence_items)
    state = {
        "normalized_query": "系统默认超时时间是多少",
        "final_context": original_context,
        "evidence_items": evidence_items,
        "citation_catalog": build_citation_catalog(evidence_items),
        "stage_summaries": {},
    }
    chat_model = _FakeChatModel(
        {
            "parsed": {
                "decision": "subset",
                "items": [
                    {
                        "citation_id": "S9",
                        "excerpt": "不存在的引用。",
                    }
                ],
            },
            "parsing_error": None,
        }
    )

    result = await _compress_context(
        state,
        runtime=SimpleNamespace(),
        settings=SimpleNamespace(),
        chat_model=chat_model,
    )

    assert chat_model.calls, "应通过 with_structured_output 走结构化主路径"
    assert result["compression_stats"]["fallback_used"] is True
    assert result["compression_stats"]["fallback_reason"] == "invalid_compressed_citation_labels"
    assert result["final_context"] == original_context
    assert [item["citation_id"] for item in result["evidence_items"]] == ["S1", "S2"]
