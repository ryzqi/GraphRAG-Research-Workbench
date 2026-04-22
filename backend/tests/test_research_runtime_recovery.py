from __future__ import annotations

import json

from app.services.research_runtime_recovery import (
    DeepResearchStructuredResponse,
    _recover_structured_response_payload,
    _normalize_structured_response_payload,
)


def _long_excerpt_text() -> str:
    return "公开资料显示 Responses API 更强调统一输入输出与工具编排。" * 30


def test_recover_structured_response_payload_accepts_missing_retrieved_at_and_long_excerpt() -> None:
    raw_payload = {
        "findings": [
            "Responses API 更适合需要工具调用、结构化输出和多模态输入的一体化任务。",
            "Chat Completions API 仍适合传统消息式对话，但新能力更集中在 Responses API。",
        ],
        "citations": [
            {
                "source_type": "web",
                "source_provider": "openai",
                "retrieval_method": "web_search",
                "source_id": "https://platform.openai.com/docs/guides/responses-vs-chat-completions",
                "title": "Responses vs. chat completions",
                "url": "https://platform.openai.com/docs/guides/responses-vs-chat-completions",
                "excerpts": [
                    {
                        "text": _long_excerpt_text(),
                        "locator": "section-1",
                        "lang": "zh",
                    }
                ],
            },
            {
                "source_type": "web",
                "source_provider": "openai",
                "retrieval_method": "web_search",
                "source_id": "https://platform.openai.com/docs/api-reference/chat",
                "title": "Chat Completions",
                "url": "https://platform.openai.com/docs/api-reference/chat",
                "origin_url": "https://platform.openai.com/docs/api-reference/chat",
                "excerpts": [
                    {
                        "text": _long_excerpt_text(),
                    }
                ],
            },
        ],
    }

    parsed = _recover_structured_response_payload(
        {
            "messages": [
                {
                    "content": json.dumps(raw_payload, ensure_ascii=False),
                }
            ]
        }
    )

    assert parsed is not None


def test_normalize_structured_response_payload_repairs_recovery_citations() -> None:
    payload = {
        "findings": [
            "Responses API 在官方定位上承载更多内建能力。",
            "Chat Completions API 更接近传统消息补全接口。",
        ],
        "citations": [
            {
                "source_type": "web",
                "source_provider": "openai",
                "retrieval_method": "web_search",
                "source_id": "https://platform.openai.com/docs/guides/responses-vs-chat-completions",
                "title": "Responses vs. chat completions",
                "url": "https://platform.openai.com/docs/guides/responses-vs-chat-completions",
                "excerpts": [
                    {
                        "text": _long_excerpt_text(),
                        "locator": "  sec-1  ",
                        "lang": "invalid",
                    }
                ],
            },
            {
                "source_type": "paper",
                "source_provider": "arxiv",
                "retrieval_method": "search",
                "source_id": "arxiv:2501.09136v4",
                "title": "Agentic Retrieval-Augmented Generation",
                "url": "https://arxiv.org/html/2501.09136v4",
                "origin_url": "https://arxiv.org/html/2501.09136v4",
                "arxiv_id": "2501.09136v4",
                "excerpts": [
                    {
                        "text": _long_excerpt_text(),
                        "lang": "mixed",
                    }
                ],
            },
        ],
    }

    normalized = _normalize_structured_response_payload(payload)
    structured = DeepResearchStructuredResponse.model_validate(normalized)

    assert len(structured.citations) == 2
    assert structured.citations[0].origin_url == structured.citations[0].url
    assert structured.citations[0].retrieved_at is not None
    assert structured.citations[0].excerpts[0].locator == "sec-1"
    assert structured.citations[0].excerpts[0].lang == "en"
    assert len(structured.citations[0].excerpts[0].text) == 400
    assert structured.citations[1].pdf_url == "https://arxiv.org/pdf/2501.09136v4.pdf"
