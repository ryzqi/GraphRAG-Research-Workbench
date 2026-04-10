from __future__ import annotations

from typing import cast

from app.services.research_service import ResearchService


class _SyncCommitDb:
    def __init__(self) -> None:
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1


async def test_commit_checkpoint_accepts_sync_commit_callable() -> None:
    service = cast(ResearchService, object.__new__(ResearchService))
    db = _SyncCommitDb()
    setattr(service, "_db", db)

    await service._commit_checkpoint()

    assert db.commit_calls == 1
