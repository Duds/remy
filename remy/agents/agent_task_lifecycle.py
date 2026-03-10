"""
Agent task lifecycle — OpenClaw-style limits and persistence without a separate runner.

Integrates with the single background primitive (BackgroundTaskRunner): callers
claim a slot (respecting SUBAGENT_MAX_WORKERS and SUBAGENT_MAX_DEPTH), wrap their
coroutine, and pass the wrapper to BackgroundTaskRunner.run() as usual. This
module only does book-keeping in agent_tasks; it does not run or schedule work.

No duplicate runner: BackgroundTaskRunner remains the only fire-and-forget executor.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, TypeVar

from ..config import settings

if TYPE_CHECKING:
    from ..memory.database import DatabaseManager

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AgentTaskStore:
    """
    Claim slots and record lifecycle for background work in agent_tasks.

    Use before starting a BackgroundTaskRunner task so the run is counted and
    surfaced via heartbeat (done/failed/stalled). Enforces max_workers and
    max_depth from config.
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self._db = db

    async def claim(
        self,
        worker_type: str,
        task_context: dict[str, Any],
        *,
        parent_id: str | None = None,
        depth: int = 0,
    ) -> str | None:
        """
        Reserve a slot and create a pending agent_tasks row if under limits.

        Returns task_id (str) or None if at worker limit or depth limit.
        Caller should run the work and use wrap_coro(task_id, coro) so we
        update running → done/failed; if claim returns None, caller may still
        run the work without agent_tasks book-keeping (backward compatible).
        """
        if depth > settings.subagent_max_depth:
            logger.debug(
                "agent_task claim skipped: depth %d > max_depth %d",
                depth,
                settings.subagent_max_depth,
            )
            return None

        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM agent_tasks WHERE status = 'running'"
            )
            row = await cursor.fetchone()
            running_count = (row[0] or 0) if row else 0

        if running_count >= settings.subagent_max_workers:
            logger.info(
                "agent_task claim skipped: %d running >= max_workers %d",
                running_count,
                settings.subagent_max_workers,
            )
            return None

        task_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        context_json = json.dumps(task_context)

        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO agent_tasks
                    (task_id, parent_id, worker_type, status, task_context, depth, created_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (task_id, parent_id, worker_type, context_json, depth, created_at),
            )
            await conn.commit()

        logger.debug(
            "agent_task claimed: %s type=%s depth=%d", task_id[:8], worker_type, depth
        )
        return task_id

    async def start(self, task_id: str) -> None:
        """Mark task as running and set started_at."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE agent_tasks
                SET status = 'running', started_at = ?
                WHERE task_id = ? AND status = 'pending'
                """,
                (now, task_id),
            )
            await conn.commit()

    async def complete(
        self,
        task_id: str,
        *,
        result: str | None = None,
        synthesis: str | None = None,
        error: str | None = None,
    ) -> None:
        """Mark task done or failed; set result/error and completed_at."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        status = "failed" if error else "done"
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE agent_tasks
                SET status = ?, result = ?, synthesis = ?, error = ?, completed_at = ?
                WHERE task_id = ?
                """,
                (status, result, synthesis, error, now, task_id),
            )
            await conn.commit()
        logger.debug("agent_task completed: %s status=%s", task_id[:8], status)

    def wrap_coro(
        self,
        task_id: str,
        coro: Awaitable[T],
    ) -> Awaitable[T]:
        """
        Return a coroutine that marks task running, runs coro, then marks done/failed.

        Use this as the argument to BackgroundTaskRunner.run() so agent_tasks
        stays in sync. The returned coroutine propagates the result or exception.
        """

        async def _wrapped() -> T:
            await self.start(task_id)
            try:
                out: T = await coro
                await self.complete(
                    task_id, result=out if isinstance(out, str) else None
                )
                return out
            except Exception as e:
                await self.complete(task_id, error=str(e))
                raise

        return _wrapped()  # type: ignore[return-value]


async def mark_stalled_tasks(db: "DatabaseManager") -> int:
    """
    Set status to 'stalled' for tasks running longer than SUBAGENT_STALL_MINUTES.

    Called from heartbeat so surfaced unsurfaced logic picks them up. Returns
    the number of rows updated.
    """
    from datetime import timedelta

    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=settings.subagent_stall_minutes)
    ).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                UPDATE agent_tasks
                SET status = 'stalled'
                WHERE status = 'running' AND started_at IS NOT NULL AND started_at < ?
                """,
                (cutoff,),
            )
            await conn.commit()
            n = cursor.rowcount
        if n:
            logger.info("Marked %d agent_task(s) as stalled", n)
        return n or 0
    except Exception as e:
        logger.warning("mark_stalled_tasks failed (non-fatal): %s", e)
        return 0
