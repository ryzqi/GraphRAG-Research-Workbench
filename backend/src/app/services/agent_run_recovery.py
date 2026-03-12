"""Recovery helpers for stale interactive AgentRun rows."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app.core.settings import Settings, get_settings
from app.models.agent_run import AgentRun, AgentRunStatus, AgentRunType

logger = logging.getLogger(__name__)

DEFAULT_STALE_INTERACTIVE_RUN_BATCH_SIZE = 100
STALE_INTERACTIVE_RUN_ERROR_MESSAGE = (
    "检测到服务重启前未正常收尾的历史运行，已自动标记失败，请重新提问。"
)


async def recover_stale_interactive_agent_runs(
    *,
    session,  # noqa: ANN001
    timeout_seconds: int,
    limit: int = DEFAULT_STALE_INTERACTIVE_RUN_BATCH_SIZE,
    now: datetime | None = None,
) -> int:
    current_time = now or datetime.now(timezone.utc)
    safe_limit = max(int(limit or DEFAULT_STALE_INTERACTIVE_RUN_BATCH_SIZE), 1)
    stale_before = current_time - timedelta(seconds=max(int(timeout_seconds or 0), 1))
    reference_time = sa.func.coalesce(AgentRun.started_at, AgentRun.created_at)
    stmt = (
        sa.select(AgentRun)
        .where(
            AgentRun.run_type.in_(
                [AgentRunType.KB_ANSWER, AgentRunType.GENERAL_ANSWER]
            ),
            AgentRun.status == AgentRunStatus.RUNNING,
            reference_time <= stale_before,
        )
        .order_by(reference_time.asc(), AgentRun.id.asc())
        .limit(safe_limit)
        .with_for_update(skip_locked=True)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for run in rows:
        run.status = AgentRunStatus.FAILED
        run.finished_at = current_time
        run.final_output = None
        run.error_message = STALE_INTERACTIVE_RUN_ERROR_MESSAGE
        run.stage_summaries = {
            **(run.stage_summaries if isinstance(run.stage_summaries, dict) else {}),
            "errterm": {
                "reason": "startup_stale_run_recovered",
                "message": STALE_INTERACTIVE_RUN_ERROR_MESSAGE,
                "at": current_time.isoformat(),
            },
        }
    return len(rows)


async def recover_stale_interactive_agent_runs_on_startup(
    *,
    sessionmaker,  # noqa: ANN001
    settings: Settings | None = None,
    limit: int = DEFAULT_STALE_INTERACTIVE_RUN_BATCH_SIZE,
) -> int:
    cfg = settings or get_settings()
    timeout_seconds = max(int(cfg.interactive_run_stale_timeout_seconds), 1)

    async with sessionmaker() as session:
        recovered = await recover_stale_interactive_agent_runs(
            session=session,
            timeout_seconds=timeout_seconds,
            limit=limit,
        )
        if recovered > 0:
            await session.commit()
            logger.warning(
                "Recovered stale interactive agent runs on startup",
                extra={
                    "recovered_count": recovered,
                    "timeout_seconds": timeout_seconds,
                },
            )
        else:
            await session.rollback()
        return recovered
