from __future__ import annotations

from app.services import research_service_session_ops as session_ops


def test_session_ops_module_exposes_workflow_entrypoints() -> None:
    assert callable(session_ops.submit_clarification)
    assert callable(session_ops.update_plan)
    assert callable(session_ops.start_session)
    assert callable(session_ops.stop_session)
    assert callable(session_ops.execute_session)
    assert callable(session_ops.fail_session)