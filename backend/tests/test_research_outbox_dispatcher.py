from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.worker.tasks import research_outbox_dispatcher


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


def _build_fake_resources(*, session: _FakeSession):
    @asynccontextmanager
    async def _session_scope():
        yield session

    @asynccontextmanager
    async def _resource_scope(*, settings, with_engine):  # noqa: ANN001
        del settings, with_engine
        yield SimpleNamespace(sessionmaker=_session_scope)

    return _resource_scope


@pytest.mark.asyncio
async def test_dispatch_research_outbox_uses_broker_visibility_timeout_as_stale_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeSession()
    observed_stale_seconds: list[int] = []

    async def _fake_recover_stale_dispatched_rows(
        *,
        session,
        limit: int,
        stale_dispatched_seconds: int,
        now=None,
    ) -> int:
        del now
        assert session is fake_session
        assert limit == 3
        observed_stale_seconds.append(stale_dispatched_seconds)
        return 0

    async def _fake_claim_due_outbox_rows(*, session, limit: int):  # noqa: ANN001
        del session, limit
        return []

    monkeypatch.setattr(
        research_outbox_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(
            celery_broker_visibility_timeout_seconds=7200,
            research_outbox_stale_dispatched_seconds=None,
        ),
    )
    monkeypatch.setattr(
        research_outbox_dispatcher,
        "managed_task_resources",
        _build_fake_resources(session=fake_session),
    )
    monkeypatch.setattr(
        research_outbox_dispatcher,
        "_recover_stale_dispatched_rows",
        _fake_recover_stale_dispatched_rows,
    )
    monkeypatch.setattr(
        research_outbox_dispatcher,
        "_claim_due_outbox_rows",
        _fake_claim_due_outbox_rows,
    )

    dispatched_rows = await research_outbox_dispatcher._dispatch_research_outbox(limit=3)

    assert dispatched_rows == 0
    assert observed_stale_seconds == [7200]
    assert fake_session.rollback_calls == 1


@pytest.mark.asyncio
async def test_dispatch_research_outbox_prefers_explicit_stale_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session = _FakeSession()
    observed_stale_seconds: list[int] = []

    async def _fake_recover_stale_dispatched_rows(
        *,
        session,
        limit: int,
        stale_dispatched_seconds: int,
        now=None,
    ) -> int:
        del now
        assert session is fake_session
        assert limit == 2
        observed_stale_seconds.append(stale_dispatched_seconds)
        return 0

    async def _fake_claim_due_outbox_rows(*, session, limit: int):  # noqa: ANN001
        del session, limit
        return []

    monkeypatch.setattr(
        research_outbox_dispatcher,
        "get_settings",
        lambda: SimpleNamespace(
            celery_broker_visibility_timeout_seconds=7200,
            research_outbox_stale_dispatched_seconds=180,
        ),
    )
    monkeypatch.setattr(
        research_outbox_dispatcher,
        "managed_task_resources",
        _build_fake_resources(session=fake_session),
    )
    monkeypatch.setattr(
        research_outbox_dispatcher,
        "_recover_stale_dispatched_rows",
        _fake_recover_stale_dispatched_rows,
    )
    monkeypatch.setattr(
        research_outbox_dispatcher,
        "_claim_due_outbox_rows",
        _fake_claim_due_outbox_rows,
    )

    dispatched_rows = await research_outbox_dispatcher._dispatch_research_outbox(limit=2)

    assert dispatched_rows == 0
    assert observed_stale_seconds == [180]
    assert fake_session.rollback_calls == 1
