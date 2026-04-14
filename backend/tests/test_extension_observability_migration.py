from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "f4c6d8e0a1b2_drop_tool_extension_observability_config.py"
)


def test_extension_observability_drop_migration_exists_and_links_from_current_head() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'down_revision = "e8f9a0b1c2d3"' in source
    assert 'op.drop_column("tool_extensions", "observability_config")' in source


def test_extension_observability_drop_migration_restores_jsonb_column_on_downgrade() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'op.add_column("tool_extensions",' in source
    assert '"observability_config"' in source
    assert "postgresql.JSONB" in source
    assert "nullable=True" in source
