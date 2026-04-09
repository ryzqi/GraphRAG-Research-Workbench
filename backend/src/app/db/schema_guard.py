from __future__ import annotations

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

EXPECTED_INGESTION_ENUM_VALUES: tuple[str, str] = ("processing", "completed")
INGESTION_STATUS_ENUM_NAMES: tuple[str, str] = (
    "ingestion_batch_status",
    "ingestion_doc_status",
)


class IngestionSchemaNotReadyError(RuntimeError):
    """当数据库尚未初始化或缺少 ingestion 枚举时抛出。"""


class IngestionSchemaMismatchError(RuntimeError):
    """当数据库中的 ingestion 枚举与应用契约不一致时抛出。"""


def validate_ingestion_enum_values(
    enum_values_by_name: Mapping[str, Sequence[str]],
) -> None:
    expected = set(EXPECTED_INGESTION_ENUM_VALUES)
    for enum_name in INGESTION_STATUS_ENUM_NAMES:
        labels = tuple(enum_values_by_name.get(enum_name, ()))
        if not labels:
            raise IngestionSchemaNotReadyError(
                "Ingestion schema not ready: "
                f"{enum_name} is missing or has no labels. "
                "Please run alembic upgrade head."
            )
        if set(labels) == expected and len(labels) == len(expected):
            continue
        raise IngestionSchemaMismatchError(
            "Ingestion status enum mismatch: "
            f"{enum_name}={list(labels)!r}, "
            f"expected={list(EXPECTED_INGESTION_ENUM_VALUES)!r}. "
            "Please run alembic upgrade head."
        )


async def _fetch_enum_labels(conn: AsyncConnection, enum_name: str) -> tuple[str, ...]:
    stmt = sa.text(
        """
        SELECT e.enumlabel
        FROM pg_type t
        JOIN pg_enum e ON t.oid = e.enumtypid
        WHERE t.typname = :enum_name
        ORDER BY e.enumsortorder
        """
    )
    result = await conn.execute(stmt, {"enum_name": enum_name})
    return tuple(result.scalars().all())


async def ensure_ingestion_schema_ready(engine: AsyncEngine) -> None:
    enum_values_by_name: dict[str, tuple[str, ...]] = {}
    async with engine.connect() as conn:
        for enum_name in INGESTION_STATUS_ENUM_NAMES:
            enum_values_by_name[enum_name] = await _fetch_enum_labels(conn, enum_name)

    validate_ingestion_enum_values(enum_values_by_name)
