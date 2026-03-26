from __future__ import annotations

from pathlib import Path


def test_alembic_ini_is_decodable_with_windows_gbk_locale() -> None:
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    raw = alembic_ini.read_bytes()

    decoded = raw.decode("gbk")

    assert "[alembic]" in decoded
    assert "sqlalchemy.url =" in decoded
