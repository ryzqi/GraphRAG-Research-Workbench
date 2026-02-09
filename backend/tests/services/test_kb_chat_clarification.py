from app.services.kb_chat_service import KbChatService


def test_extract_clarification_message_from_answer() -> None:
    message = KbChatService._extract_clarification_message(
        stage_summaries={"force_exit": {"reason": "clarify"}},
        answer="请补充时间范围。",
    )
    assert message == "请补充时间范围。"


def test_extract_clarification_message_fallback_when_answer_empty() -> None:
    message = KbChatService._extract_clarification_message(
        stage_summaries={"force_exit": {"reason": "clarify"}},
        answer="   ",
    )
    assert message == "为了更准确地回答，请补充必要信息后再提问。"


def test_extract_clarification_message_returns_none_when_not_clarify() -> None:
    message = KbChatService._extract_clarification_message(
        stage_summaries={"force_exit": {"reason": "max_total_rounds"}},
        answer="irrelevant",
    )
    assert message is None
