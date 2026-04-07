from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
START_BACKEND_SCRIPT = ROOT / "scripts" / "start_backend_api.ps1"
START_ALL_SCRIPT = ROOT / "scripts" / "start_all.ps1"
VERIFY_QUICKSTART_SCRIPT = ROOT / "scripts" / "verify_quickstart.ps1"
README_PATH = ROOT / "README.md"


def test_start_backend_script_is_removed() -> None:
    assert START_BACKEND_SCRIPT.exists() is False


def test_start_all_embeds_selector_loop_backend_command() -> None:
    text = START_ALL_SCRIPT.read_text(encoding="utf-8")

    assert "uvicorn app.main:app" in text
    assert "windows_selector_loop_factory" in text
    assert "start_backend_api.ps1" not in text


def test_windows_backend_entrypoint_is_documented_consistently() -> None:
    start_all = START_ALL_SCRIPT.read_text(encoding="utf-8")
    verify = VERIFY_QUICKSTART_SCRIPT.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "start_backend_api.ps1" not in start_all
    assert "start_backend_api.ps1" not in verify
    assert "start_backend_api.ps1" not in readme
    assert "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop app.core.uvicorn_loop:windows_selector_loop_factory" in readme


def test_start_all_uses_approved_powershell_verbs_for_custom_functions() -> None:
    text = START_ALL_SCRIPT.read_text(encoding="utf-8")

    assert "function Ensure-Command" not in text
    assert "function Normalize-ApiBaseUrl" not in text
    assert "function Assert-Command" in text
    assert "function Resolve-ApiBaseUrl" in text
    assert "Assert-Command -Name \"uv\"" in text
    assert "Assert-Command -Name \"npm\"" in text
    assert "Resolve-ApiBaseUrl -Raw $rawApiBase" in text
    assert "Resolve-ApiBaseUrl -Raw $env:VITE_API_BASE_URL" in text
