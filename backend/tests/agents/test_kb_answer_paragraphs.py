from __future__ import annotations

from typing import Any, get_type_hints

from app.agents.kb_chat_agentic.schemas import AnswerParagraph, ParagraphClaim
from app.agents.kb_chat_agentic_state import (
    AnswerCommitInput,
    AnswerRepairInput,
    AnswerReviewCitationInput,
    AnswerReviewInput,
    DraftGenerateInput,
    KbChatInternalState,
    KbChatOutputState,
)
from app.services.kb_answer_paragraphs import (
    prune_unsupported_auxiliary_claims,
    render_answer_paragraphs,
)


def test_render_answer_paragraphs_appends_paragraph_citations_at_tail() -> None:
    paragraphs = [
        AnswerParagraph(
            paragraph_id="p1",
            text="CoT 适合单路径逻辑推理。",
            citation_ids=["S1", "S3"],
            claims=[],
            review_status="passed",
        )
    ]

    assert render_answer_paragraphs(paragraphs) == "CoT 适合单路径逻辑推理。[S1][S3]"


def test_prune_unsupported_auxiliary_claims_keeps_supported_main_text_and_citations() -> None:
    paragraphs = [
        AnswerParagraph(
            paragraph_id="p1",
            text="CoT 适合单路径逻辑推理。它总能优于 Tree of Thoughts。",
            citation_ids=["S1", "S2"],
            claims=[
                ParagraphClaim(
                    claim_id="c1",
                    claim_text="CoT 适合单路径逻辑推理。",
                    role="main",
                    support_status="supported",
                    supporting_citation_ids=["S1"],
                ),
                ParagraphClaim(
                    claim_id="c2",
                    claim_text="它总能优于 Tree of Thoughts。",
                    role="auxiliary",
                    support_status="unsupported",
                    supporting_citation_ids=["S2"],
                ),
            ],
            review_status="needs_repair",
        )
    ]

    pruned = prune_unsupported_auxiliary_claims(paragraphs)

    assert pruned == [
        AnswerParagraph(
            paragraph_id="p1",
            text="CoT 适合单路径逻辑推理。",
            citation_ids=["S1"],
            claims=[
                ParagraphClaim(
                    claim_id="c1",
                    claim_text="CoT 适合单路径逻辑推理。",
                    role="main",
                    support_status="supported",
                    supporting_citation_ids=["S1"],
                )
            ],
            review_status="needs_repair",
        )
    ]


def test_prune_unsupported_auxiliary_claims_rebuilds_text_from_kept_claims_in_order() -> None:
    paragraphs = [
        AnswerParagraph(
            paragraph_id="p2",
            text="CoT 适合单路径逻辑推理。CoT 适合单路径逻辑推理。另一个已保留结论。",
            citation_ids=["S1", "S2", "S3"],
            claims=[
                ParagraphClaim(
                    claim_id="c1",
                    claim_text="CoT 适合单路径逻辑推理。",
                    role="main",
                    support_status="supported",
                    supporting_citation_ids=["S1"],
                ),
                ParagraphClaim(
                    claim_id="c2",
                    claim_text="CoT 适合单路径逻辑推理。",
                    role="auxiliary",
                    support_status="unsupported",
                    supporting_citation_ids=["S2"],
                ),
                ParagraphClaim(
                    claim_id="c3",
                    claim_text="另一个已保留结论。",
                    role="main",
                    support_status="weak_supported",
                    supporting_citation_ids=["S3"],
                ),
            ],
            review_status="needs_repair",
        )
    ]

    pruned = prune_unsupported_auxiliary_claims(paragraphs)

    assert pruned == [
        AnswerParagraph(
            paragraph_id="p2",
            text="CoT 适合单路径逻辑推理。另一个已保留结论。",
            citation_ids=["S1", "S3"],
            claims=[
                ParagraphClaim(
                    claim_id="c1",
                    claim_text="CoT 适合单路径逻辑推理。",
                    role="main",
                    support_status="supported",
                    supporting_citation_ids=["S1"],
                ),
                ParagraphClaim(
                    claim_id="c3",
                    claim_text="另一个已保留结论。",
                    role="main",
                    support_status="weak_supported",
                    supporting_citation_ids=["S3"],
                ),
            ],
            review_status="needs_repair",
        )
    ]


def test_kb_chat_state_uses_state_friendly_answer_paragraph_contract() -> None:
    required_annotations = {
        "KbChatInternalState": get_type_hints(KbChatInternalState),
        "KbChatOutputState": get_type_hints(KbChatOutputState),
        "DraftGenerateInput": get_type_hints(DraftGenerateInput),
        "AnswerReviewCitationInput": get_type_hints(AnswerReviewCitationInput),
        "AnswerReviewInput": get_type_hints(AnswerReviewInput),
        "AnswerRepairInput": get_type_hints(AnswerRepairInput),
        "AnswerCommitInput": get_type_hints(AnswerCommitInput),
    }

    for name, annotation_map in required_annotations.items():
        assert annotation_map["answer_paragraphs"] == list[dict[str, Any]], name
        assert annotation_map["answer_render_meta"] == dict[str, Any], name
