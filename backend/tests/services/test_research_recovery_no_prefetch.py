"""recovery 不再做 prefetch / 全量回捞。"""

from app.services import research_runtime_recovery as rr


def test_prefetch_and_recover_helpers_are_removed() -> None:
    forbidden = {
        "_needs_external_evidence_prefetch",
        "_prefetch_required_external_tool_messages",
        "_build_prefetched_tool_message",
        "_recover_tool_evidence_citation_payloads",
        "_merge_recovered_citations_into_payload",
        "_dedupe_recovered_citation_payloads",
        "_recover_citation_payload_from_tool_result",
    }
    for name in forbidden:
        assert not hasattr(rr, name), f"recovery 仍暴露已废弃符号 {name}"


def test_continue_limit_reduced_to_one() -> None:
    assert rr._MISSING_STRUCTURED_RESPONSE_CONTINUE_LIMIT == 1
