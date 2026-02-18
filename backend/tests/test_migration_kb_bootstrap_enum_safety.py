from __future__ import annotations

from pathlib import Path


def test_kb_bootstrap_status_enum_contains_direct_upload_state() -> None:
    files = sorted(Path("alembic/versions").glob("*.py"))
    assert len(files) == 1, f"Expected one squashed migration file, got: {[p.name for p in files]}"
    migration = files[0].read_text(encoding="utf-8")

    assert "kb_bootstrap_job_status" in migration
    assert "queued_upload" in migration
