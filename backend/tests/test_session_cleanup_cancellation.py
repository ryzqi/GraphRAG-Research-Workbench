from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.api.dependencies import services as service_dependencies
from app.db import session as db_session


class _FakeSession:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.close_succeeded = asyncio.Event()
        self.close_cancelled = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        self.close_started.set()
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.close_cancelled = True
            raise
        else:
            self.close_succeeded.set()


class _FakeSessionmaker:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSession:
        return self._session


def test_get_db_session_finishes_close_when_generator_cleanup_is_cancelled(
    monkeypatch,
) -> None:
    async def _exercise() -> None:
        fake_session = _FakeSession()
        monkeypatch.setattr(
            db_session,
            "get_sessionmaker",
            lambda: _FakeSessionmaker(fake_session),
        )

        generator = db_session.get_db_session()
        yielded = await anext(generator)
        assert yielded is fake_session

        closer = asyncio.create_task(generator.aclose())
        await fake_session.close_started.wait()
        closer.cancel()
        try:
            await closer
        except asyncio.CancelledError:
            pass

        await asyncio.wait_for(fake_session.close_succeeded.wait(), timeout=0.2)
        assert fake_session.close_cancelled is False

    asyncio.run(_exercise())


def test_open_service_scope_finishes_close_when_scope_exit_is_cancelled(
    monkeypatch,
) -> None:
    async def _exercise() -> None:
        fake_session = _FakeSession()
        monkeypatch.setattr(
            service_dependencies,
            "create_sessionmaker",
            lambda engine: _FakeSessionmaker(fake_session),
        )

        scope = service_dependencies._open_service_scope(
            resources=SimpleNamespace(engine=object()),
            factory=lambda db: ("service", db),
        )
        yielded_db, yielded_service = await scope.__aenter__()
        assert yielded_db is fake_session
        assert yielded_service == ("service", fake_session)

        closer = asyncio.create_task(scope.__aexit__(None, None, None))
        await fake_session.close_started.wait()
        closer.cancel()
        try:
            await closer
        except asyncio.CancelledError:
            pass

        await asyncio.wait_for(fake_session.close_succeeded.wait(), timeout=0.2)
        assert fake_session.close_cancelled is False

    asyncio.run(_exercise())
