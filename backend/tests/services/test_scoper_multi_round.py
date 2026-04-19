"""scoper 支持多轮 clarification（默认 2 轮）。"""

from app.core.settings import get_settings
from app.models.research_session import ResearchSession
from app.services.research_service import ResearchService


class _FakeEvents(list):
    def __init__(self, answers: list[str]) -> None:
        super().__init__()
        for index, answer in enumerate(answers, start=1):
            self.append(
                type(
                    "Event",
                    (),
                    {
                        "event_type": "research.clarification.submitted",
                        "sequence": index,
                        "payload": {"answer": answer},
                    },
                )()
            )


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_follow_up_allowed_when_rounds_under_max(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SCOPER_MAX_CLARIFY_ROUNDS", "2")
    _clear_settings_cache()
    try:
        session = ResearchSession(question="q")
        session.__dict__["events"] = _FakeEvents(["a1"])
        assert ResearchService._should_allow_follow_up_clarification(
            session=session,
            answer="a2",
        ) is True
    finally:
        _clear_settings_cache()


def test_follow_up_forbidden_once_rounds_reach_max(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SCOPER_MAX_CLARIFY_ROUNDS", "2")
    _clear_settings_cache()
    try:
        session = ResearchSession(question="q")
        session.__dict__["events"] = _FakeEvents(["a1", "a2"])
        assert ResearchService._should_allow_follow_up_clarification(
            session=session,
            answer="a3",
        ) is False
    finally:
        _clear_settings_cache()
