from __future__ import annotations

import subprocess
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]


def _render_upgrade_sql(target_revision: str) -> str:
    completed = subprocess.run(
        ["uv", "run", "alembic", "upgrade", target_revision, "--sql"],
        cwd=BACKEND_DIR,
        capture_output=True,
        check=True,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    return stdout + stderr


def test_reintroduce_research_session_migration_recreates_enum_before_table() -> None:
    sql = _render_upgrade_sql("38f4aa0f8d91")
    marker = "-- Running upgrade a6b8c9d0e1f2 -> 38f4aa0f8d91"

    assert marker in sql, "应能定位到 38f4aa0f8d91 的离线迁移 SQL 段"

    section = sql.split(marker, maxsplit=1)[1]
    create_type = "CREATE TYPE research_session_status AS ENUM"
    create_table = "CREATE TABLE research_sessions"

    assert create_type in section, "重新引入 research_sessions 前必须先重建 research_session_status enum"
    assert section.index(create_type) < section.index(create_table)
