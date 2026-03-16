from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_importing_requests_has_no_dependency_warning() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-W", "default", "-c", "import requests"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined_output = "\n".join(
        part for part in (result.stdout.strip(), result.stderr.strip()) if part
    )
    assert "RequestsDependencyWarning" not in combined_output, combined_output
