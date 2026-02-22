from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.checkpoint import CheckpointManager
from app.db.session import create_sessionmaker
from app.models.chat_session import ChatSession, ChatSessionType


async def _run(*, dry_run: bool, limit: int | None) -> None:
    sessionmaker = create_sessionmaker()
    await CheckpointManager.initialize()
    try:
        async with sessionmaker() as session:
            stmt = select(ChatSession.id).where(
                ChatSession.session_type == ChatSessionType.GENERAL_CHAT
            )
            if isinstance(limit, int) and limit > 0:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            thread_ids = [str(row[0]) for row in result.all()]

        print(f"general_chat sessions: {len(thread_ids)}")
        if dry_run:
            print("dry-run enabled, no checkpoint deleted")
            return

        deleted = 0
        for thread_id in thread_ids:
            await CheckpointManager.delete_thread(thread_id)
            deleted += 1

        print(f"deleted checkpoints: {deleted}")
    finally:
        await CheckpointManager.shutdown()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bulk delete checkpoints for all general_chat sessions."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print candidate sessions without deleting checkpoints.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of sessions to process.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(_run(dry_run=args.dry_run, limit=args.limit))
