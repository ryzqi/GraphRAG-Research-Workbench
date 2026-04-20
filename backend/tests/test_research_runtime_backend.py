from __future__ import annotations

import pytest

from app.services.research_runtime_factory import build_research_backend


@pytest.mark.asyncio
async def test_research_backend_batch_download_uses_workspace_seed_backend_without_hash_error() -> None:
    backend = build_research_backend()

    responses = await backend.adownload_files(["/missing.txt"])

    assert len(responses) == 1
    assert responses[0].path == "/missing.txt"
    assert responses[0].content is None
    assert responses[0].error == "file_not_found"
