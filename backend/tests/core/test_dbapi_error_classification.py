from __future__ import annotations

from app.core.errors import _classify_dbapi_error


def test_classify_dbapi_error_marks_enum_drift_as_schema_not_ready() -> None:
    reason = (
        "<class 'asyncpg.exceptions.InvalidTextRepresentationError'>: "
        "invalid input value for enum ingestion_batch_status: \"processing\""
    )

    status_code, code, message = _classify_dbapi_error(
        reason=reason,
        connection_invalidated=False,
    )

    assert status_code == 503
    assert code == "DATABASE_SCHEMA_NOT_READY"
    assert "alembic upgrade head" in message


def test_classify_dbapi_error_marks_missing_table_as_schema_not_ready() -> None:
    status_code, code, _ = _classify_dbapi_error(
        reason="UndefinedTableError: relation ingestion_batches does not exist",
        connection_invalidated=False,
    )

    assert status_code == 503
    assert code == "DATABASE_SCHEMA_NOT_READY"


def test_classify_dbapi_error_marks_connection_invalidated_as_unavailable() -> None:
    status_code, code, _ = _classify_dbapi_error(
        reason="connection lost",
        connection_invalidated=True,
    )

    assert status_code == 503
    assert code == "DATABASE_UNAVAILABLE"


def test_classify_dbapi_error_marks_other_errors_as_database_error() -> None:
    status_code, code, _ = _classify_dbapi_error(
        reason="some unknown DBAPI exception",
        connection_invalidated=False,
    )

    assert status_code == 500
    assert code == "DATABASE_ERROR"
