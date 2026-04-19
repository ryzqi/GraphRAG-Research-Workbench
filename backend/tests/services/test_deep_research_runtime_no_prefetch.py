"""run_session 中不再有 prefetch 分支。"""

from pathlib import Path


def test_runner_does_not_reference_prefetch() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "app"
        / "services"
        / "deep_research_runtime.py"
    ).read_text(encoding="utf-8")
    run_session_source = source.split("async def run_session(", 1)[1].split(
        "\n\nasync def build_deep_research_runtime_runner", 1
    )[0]

    assert "_needs_external_evidence_prefetch" not in run_session_source
    assert "_prefetch_required_external_tool_messages" not in run_session_source
    assert "_recover_tool_evidence_citation_payloads" not in run_session_source
