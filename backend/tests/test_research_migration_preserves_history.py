from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from app.core.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
LEGACY_HEAD_REVISION = "f3a2c1d4e5b6"


def _asyncpg_kwargs(url: URL) -> dict[str, object]:
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host,
        "port": url.port,
        "database": url.database,
    }


@contextmanager
def _override_database_url(database_url: str) -> Iterator[None]:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def _build_alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("prepend_sys_path", str(BACKEND_DIR / "src"))
    return config


def _upgrade_database(database_url: str, revision: str) -> None:
    with _override_database_url(database_url):
        command.upgrade(_build_alembic_config(), revision)


def _normalize_json_value(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(stripped)
    return value


async def _create_database(admin_url: URL, database_name: str) -> None:
    conn = await asyncpg.connect(**_asyncpg_kwargs(admin_url))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await conn.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await conn.close()


async def _drop_database(admin_url: URL, database_name: str) -> None:
    conn = await asyncpg.connect(**_asyncpg_kwargs(admin_url))
    try:
        await conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = $1
              AND pid <> pg_backend_pid()
            """,
            database_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await conn.close()


@contextmanager
def _temporary_database(base_database_url: str) -> Iterator[str]:
    base_url = make_url(base_database_url)
    admin_url = base_url.set(database="postgres")
    database_name = f"mkb_migration_preserve_{uuid.uuid4().hex}"
    asyncio.run(_create_database(admin_url, database_name))
    try:
        yield base_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        asyncio.run(_drop_database(admin_url, database_name))


async def _seed_legacy_research_data(database_url: str) -> dict[str, uuid.UUID | str]:
    url = make_url(database_url)
    conn = await asyncpg.connect(**_asyncpg_kwargs(url))
    try:
        session_id = uuid.uuid4()
        legacy_run_id = uuid.uuid4()
        artifact_id = uuid.uuid4()
        event_id = uuid.uuid4()
        report_id = uuid.uuid4()
        trace_id = "trace-legacy-001"
        thread_id = "thread-legacy-001"
        question = "旧链路中的研究问题"
        legacy_report_md = "# Legacy Report\n\n迁移前的研究结论。"
        legacy_citations = json.dumps(
            [
                {
                    "source_type": "web",
                    "source_provider": "legacy-import",
                    "retrieval_method": "legacy-report",
                    "source_id": "https://example.com/legacy-report",
                    "origin_url": "https://example.com/legacy-report",
                    "title": "Legacy Report Source",
                }
            ]
        )

        await conn.execute(
            """
            INSERT INTO agent_runs (
                id,
                run_type,
                session_id,
                question,
                selected_kb_ids,
                allow_external,
                mode,
                status,
                stage_summaries,
                final_output,
                metrics,
                error_message,
                created_at,
                started_at,
                finished_at
            )
            VALUES (
                $1,
                'research',
                NULL,
                $2,
                NULL,
                false,
                'single_agent',
                'succeeded',
                NULL,
                NULL,
                NULL,
                NULL,
                now(),
                now(),
                now()
            )
            """,
            legacy_run_id,
            question,
        )
        await conn.execute(
            """
            INSERT INTO research_sessions (
                id,
                thread_id,
                question,
                selected_kb_ids,
                allow_external,
                mode,
                status,
                stage_summaries,
                metrics,
                final_output,
                error_message,
                trace_id,
                last_event_sequence,
                last_resume_idempotency_key,
                last_resume_response,
                legacy_run_id,
                created_at,
                started_at,
                finished_at,
                updated_at
            )
            VALUES (
                $1,
                $2,
                $3,
                NULL,
                false,
                'single_agent',
                'final',
                NULL,
                $4::jsonb,
                NULL,
                NULL,
                $5,
                1,
                NULL,
                NULL,
                $6,
                now(),
                now(),
                now(),
                now()
            )
            """,
            session_id,
            thread_id,
            question,
            json.dumps({"legacy": True}),
            trace_id,
            legacy_run_id,
        )
        await conn.execute(
            """
            INSERT INTO research_artifacts (
                id,
                session_id,
                artifact_key,
                content_text,
                content_json,
                created_at,
                updated_at
            )
            VALUES (
                $1,
                $2,
                'legacy_note',
                'legacy artifact payload',
                NULL,
                now(),
                now()
            )
            """,
            artifact_id,
            session_id,
        )
        await conn.execute(
            """
            INSERT INTO research_events (
                id,
                session_id,
                event_id,
                sequence,
                event_type,
                payload,
                trace_id,
                idempotency_key,
                created_at
            )
            VALUES (
                $1,
                $2,
                'evt-legacy-001',
                1,
                'research.run.started',
                $3::jsonb,
                $4,
                NULL,
                now()
            )
            """,
            event_id,
            session_id,
            json.dumps({"legacy": True}),
            trace_id,
        )
        await conn.execute(
            """
            INSERT INTO research_reports (
                id,
                run_id,
                content_md,
                citations,
                created_at
            )
            VALUES (
                $1,
                $2,
                $3,
                $4::jsonb,
                now()
            )
            """,
            report_id,
            legacy_run_id,
            legacy_report_md,
            legacy_citations,
        )
        return {
            "session_id": session_id,
            "thread_id": thread_id,
            "question": question,
            "trace_id": trace_id,
            "legacy_report_md": legacy_report_md,
        }
    finally:
        await conn.close()


async def _load_preserved_state(
    database_url: str,
    *,
    session_id: uuid.UUID,
) -> dict[str, object]:
    url = make_url(database_url)
    conn = await asyncpg.connect(**_asyncpg_kwargs(url))
    try:
        session_row = await conn.fetchrow(
            """
            SELECT id, thread_id, question, status, trace_id
            FROM research_sessions
            WHERE id = $1
            """,
            session_id,
        )
        artifact_rows = await conn.fetch(
            """
            SELECT artifact_key, content_text, content_json
            FROM research_artifacts
            WHERE session_id = $1
            ORDER BY artifact_key
            """,
            session_id,
        )
        event_rows = await conn.fetch(
            """
            SELECT event_id, event_type, phase, namespace, payload
            FROM research_events
            WHERE session_id = $1
            ORDER BY sequence
            """,
            session_id,
        )
        report_table = await conn.fetchval("SELECT to_regclass('public.research_reports')")
        backup_tables = await conn.fetch(
            """
            SELECT relname
            FROM pg_class
            WHERE relname LIKE 'migration_backup_research_%'
            ORDER BY relname
            """
        )
        return {
            "session": dict(session_row) if session_row is not None else None,
            "artifacts": [
                {
                    **dict(row),
                    "content_json": _normalize_json_value(row["content_json"]),
                }
                for row in artifact_rows
            ],
            "events": [
                {
                    **dict(row),
                    "payload": _normalize_json_value(row["payload"]),
                }
                for row in event_rows
            ],
            "report_table": report_table,
            "backup_tables": [str(row["relname"]) for row in backup_tables],
        }
    finally:
        await conn.close()


def test_upgrade_from_legacy_research_schema_preserves_research_history() -> None:
    base_database_url = get_settings().database_url

    with _temporary_database(base_database_url) as database_url:
        _upgrade_database(database_url, LEGACY_HEAD_REVISION)
        seeded = asyncio.run(_seed_legacy_research_data(database_url))

        _upgrade_database(database_url, "head")
        state = asyncio.run(
            _load_preserved_state(
                database_url,
                session_id=seeded["session_id"],
            )
        )

    assert state["session"] == {
        "id": seeded["session_id"],
        "thread_id": seeded["thread_id"],
        "question": seeded["question"],
        "status": "final",
        "trace_id": seeded["trace_id"],
    }

    artifact_by_key = {
        row["artifact_key"]: row
        for row in state["artifacts"]
    }
    assert set(artifact_by_key) >= {"legacy_note", "report_md", "report_json"}
    assert artifact_by_key["legacy_note"]["content_text"] == "legacy artifact payload"
    assert artifact_by_key["report_md"]["content_text"] == seeded["legacy_report_md"]
    assert artifact_by_key["report_json"]["content_json"] == {
        "legacy_report": True,
        "report_md": seeded["legacy_report_md"],
        "citations": [
            {
                "origin_url": "https://example.com/legacy-report",
                "retrieval_method": "legacy-report",
                "source_id": "https://example.com/legacy-report",
                "source_provider": "legacy-import",
                "source_type": "web",
                "title": "Legacy Report Source",
            }
        ],
        "claim_map": [],
        "coverage_matrix": {
            "provider_counts": {},
            "missing_providers": [],
        },
        "conflicts": [],
        "source_ledger": [],
    }

    assert state["events"] == [
        {
            "event_id": "evt-legacy-001",
            "event_type": "research.run.started",
            "phase": "legacy",
            "namespace": "main",
            "payload": {"legacy": True},
        }
    ]
    assert state["report_table"] is None
    assert state["backup_tables"] == []
