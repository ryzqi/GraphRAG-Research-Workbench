from __future__ import annotations

from pathlib import Path
import subprocess

from app.config.policy_loader import (
    load_frontend_runtime_policy,
    load_research_policy,
    load_search_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_policy_manifests_cover_runtime_and_search_contracts() -> None:
    search_policy = load_search_policy()
    research_policy = load_research_policy()
    frontend_policy = load_frontend_runtime_policy()

    assert search_policy.version
    assert search_policy.query_planning.multi_query_label_tokens
    assert search_policy.query_planning.ambiguity_reason_labels

    assert research_policy.version
    assert research_policy.coverage_gate.default_required_web_providers
    assert research_policy.status_probe.provider_order

    assert frontend_policy.version
    assert frontend_policy.ingestion_stream_fallback_polling_steps_ms
    assert frontend_policy.download_allowed_hosts == []


def test_query_rewrite_policy_values_do_not_fall_back_to_module_level_tables() -> None:
    legacy_constant_assignments = {
        REPO_ROOT / "backend/src/app/services/query_rewrite_text.py": (
            "_DEFAULT_CLARIFICATION_QUESTION =",
            "_AMBIGUITY_REASON_LABELS =",
            "_MULTI_QUERY_LABEL_TOKENS =",
            "_TROUBLESHOOT_KEYWORDS =",
        ),
        REPO_ROOT / "backend/src/app/search/web/query_rewrite.py": (
            "2026",
        ),
    }

    for path, forbidden_snippets in legacy_constant_assignments.items():
        source = path.read_text(encoding="utf-8")
        for forbidden_snippet in forbidden_snippets:
            assert forbidden_snippet not in source


def test_repo_hardcoded_guard_script_passes() -> None:
    script_path = REPO_ROOT / "scripts" / "check_hardcoded_config.ps1"
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
