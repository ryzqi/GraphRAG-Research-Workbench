from __future__ import annotations

from pathlib import Path


def _load_all_migrations() -> str:
    files = sorted(Path("alembic/versions").glob("*.py"))
    assert files, "Expected at least one alembic migration file."
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_kb_bootstrap_direct_upload_migration_is_present() -> None:
    migration = _load_all_migrations()
    assert "kb_bootstrap_jobs" in migration
    assert "upload_manifest" in migration
    assert "queued_upload" in migration
