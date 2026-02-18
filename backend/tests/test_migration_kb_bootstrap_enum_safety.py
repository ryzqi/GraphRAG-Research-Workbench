from __future__ import annotations

from pathlib import Path


def test_kb_bootstrap_status_enum_contains_direct_upload_state() -> None:
    files = sorted(Path("alembic/versions").glob("*.py"))
    assert files, "Expected at least one alembic migration file."
    migration = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "kb_bootstrap_job_status" in migration
    assert "queued_upload" in migration
