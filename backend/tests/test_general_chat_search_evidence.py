from app.schemas.chats import EvidenceItem
from app.services.general_chat_search_evidence import append_reference_urls_to_answer


def test_append_reference_urls_to_answer_appends_unique_urls_only() -> None:
    answer = "这是最终回答。"
    evidence = [
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://example.com/a"},
            excerpt="不应该出现在最终来源区块中的摘要 A",
            source_excerpt="网页正文 A",
            citation_source="https://example.com/a",
            citation_title="来源 A",
        ),
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://example.com/a"},
            excerpt="重复来源",
            citation_source="https://example.com/a",
            citation_title="来源 A 重复",
        ),
        EvidenceItem(
            source_kind="external",
            locator={"url": "https://example.com/b"},
            excerpt="不应该出现在最终来源区块中的摘要 B",
            source_excerpt="网页正文 B",
            citation_source="https://example.com/b",
            citation_title="来源 B",
        ),
    ]

    result = append_reference_urls_to_answer(answer, evidence)

    assert result == (
        "这是最终回答。\n\n"
        "参考来源\n"
        "- https://example.com/a\n"
        "- https://example.com/b"
    )
    assert "网页正文 A" not in result
    assert "不应该出现在最终来源区块中的摘要" not in result


def test_append_reference_urls_to_answer_keeps_original_when_no_valid_url() -> None:
    answer = "这是未联网回答。"
    evidence = [
        EvidenceItem(
            source_kind="external",
            locator={},
            excerpt="只有摘要，没有 URL",
            citation_title="无 URL 来源",
        )
    ]

    assert append_reference_urls_to_answer(answer, evidence) == answer
