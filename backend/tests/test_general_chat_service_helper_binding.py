from __future__ import annotations

from typing import cast

from app.integrations.llm_client import LLMClient
from app.services import general_chat_service as general_chat_service_module
from app.services.chat_replay_policy import ReplayDecision, ReplayMode
from app.services.general_chat_service import GeneralChatService


def _build_service() -> GeneralChatService:
    return GeneralChatService(db=object(), llm=cast(LLMClient, object()))


def test_instance_helper_registry_contains_only_self_bound_callables() -> None:
    misclassified = sorted(
        name
        for name, helper in general_chat_service_module._INSTANCE_HELPERS.items()
        if isinstance(helper, (staticmethod, classmethod))
    )

    assert misclassified == []


def test_service_exposes_static_helpers_without_binding_extra_self() -> None:
    service = _build_service()
    timeout_exc = type("APITimeoutError", (Exception,), {"__module__": "openai"})(
        "upstream timeout"
    )

    mapped = service._map_llm_exception(timeout_exc)
    replay_metrics = service._build_replay_metrics(
        ReplayDecision(
            mode=ReplayMode.MANUAL,
            use_previous_response_id=False,
            require_assistant_response_id=False,
            allow_recovery=False,
        )
    )

    assert mapped is not None
    assert mapped.code == "LLM_UPSTREAM_TIMEOUT"
    assert replay_metrics == {
        "replay": {
            "mode": "manual",
            "used_previous_response_id": False,
            "recovered": False,
        }
    }


def test_service_can_call_recovery_helper_from_instance() -> None:
    service = _build_service()
    replay_decision = ReplayDecision(
        mode=ReplayMode.AUTO,
        use_previous_response_id=True,
        require_assistant_response_id=True,
        allow_recovery=True,
    )

    error = type(
        "APIStatusError",
        (Exception,),
        {
            "__module__": "openai",
            "status_code": 404,
            "body": {"error": {"message": "Response with id resp_123 not found"}},
        },
    )("not found")

    assert service._should_recover_from_response_not_found(error, replay_decision) is True
