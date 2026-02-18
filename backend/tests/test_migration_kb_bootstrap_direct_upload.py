from __future__ import annotations

from pathlib import Path


def _load_single_migration() -> str:
    files = sorted(Path("alembic/versions").glob("*.py"))
    assert len(files) == 1, f"Expected one squashed migration file, got: {[p.name for p in files]}"
    return files[0].read_text(encoding="utf-8")


def test_kb_bootstrap_direct_upload_migration_is_present() -> None:
    migration = _load_single_migration()
    assert "kb_bootstrap_jobs" in migration
    assert "upload_manifest" in migration
    assert "queued_upload" in migration
