from __future__ import annotations

import uuid

from app.services.kb_chat_service import KbChatService


def test_build_no_evidence_response_includes_reason_and_actions() -> None:
    response = KbChatService._build_no_evidence_response(
        stage_summaries={
            "merge_context": {"completed_at": "2026-01-01T00:00:00Z"},
            "retrieval": {"reason": "max_retrieval_retries"},
            "force_exit": {"reason": "max_retrieval_retries"},
        },
        selected_kb_ids=[uuid.uuid4(), uuid.uuid4()],
    )

    assert "无法从当前知识库中找到足够证据" in response
    assert "多次重写检索后仍未命中相关证据" in response
    assert "当前知识库范围：2 个" in response
    assert "建议下一步" in response


def test_build_no_evidence_response_for_clarify_reason() -> None:
    response = KbChatService._build_no_evidence_response(
        stage_summaries={
            "ambiguity_check": {"completed_at": "2026-01-01T00:00:00Z"},
            "force_exit": {"reason": "clarify"},
        },
        selected_kb_ids=None,
    )

    assert "当前问题信息不足" in response
    assert "先补充缺失条件" in response
