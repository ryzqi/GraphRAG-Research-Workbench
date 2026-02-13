from __future__ import annotations

from types import SimpleNamespace

from app.agents.kb_chat_agentic.tool_loop import force_exit_node


def _settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        kb_chat_max_total_rounds=4,
        kb_chat_max_retrieval_retries=2,
        kb_chat_max_generation_retries=2,
    )


def test_force_exit_uses_best_answer_when_last_check_failed() -> None:
    result = force_exit_node(
        {
            "reflection": {"action": "force_exit", "answer_passed": False},
            "best_answer": "中途已校验通过的答案 [1]。",
            "draft_answer": "不稳定草稿",
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "stage_summaries": {},
        },
        _settings_stub(),
    )

    assert result["final_answer"] == "中途已校验通过的答案 [1]。"
    assert result["messages"][0].content == "中途已校验通过的答案 [1]。"
    force_exit = result["stage_summaries"]["force_exit"]
    assert force_exit["used_best_answer"] is True
    assert force_exit["answer_passed"] is False


def test_force_exit_falls_back_when_no_best_answer() -> None:
    result = force_exit_node(
        {
            "reflection": {"action": "force_exit", "answer_passed": False},
            "draft_answer": "",
            "loop_counts": {
                "total_rounds": 0,
                "retrieval_retries": 0,
                "generation_retries": 0,
            },
            "stage_summaries": {},
        },
        _settings_stub(),
    )

    assert result["final_answer"] == "根据现有资料无法回答该问题（已停止重试）。"
    force_exit = result["stage_summaries"]["force_exit"]
    assert force_exit["used_best_answer"] is False
