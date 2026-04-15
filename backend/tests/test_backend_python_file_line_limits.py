from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = BACKEND_ROOT / "src" / "app"
MAX_PYTHON_FILE_LINES = 800


def test_backend_python_files_do_not_exceed_800_lines() -> None:
    offenders: list[str] = []

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_PYTHON_FILE_LINES:
            relative_path = path.relative_to(BACKEND_ROOT).as_posix()
            offenders.append(f"{relative_path}: {line_count}")

    assert offenders == [], "超长 Python 文件:\n" + "\n".join(offenders)
