"""Task runner — manages asyncio worker task pool for the sub-agent system (SAD v10 §11).

Enforces MAX_WORKERS, MAX_DEPTH, MAX_CHILDREN. Persists all state to agent_tasks table.
Marks stalled tasks (running > SUBAGENT_STALL_MINUTES) on check_stalled() calls.
Does NOT retry failed tasks — surfaces via heartbeat so Dale decides.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..config import settings

if TYPE_CHECKING:
    from ..memory.database import DatabaseManager

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Manages the asyncio worker task pool for the sub-agent system.

    Use spawn() to create a new worker task. All status transitions are persisted
    to the agent_tasks SQLite table so they survive restarts.

    Stall detection runs via check_stalled() — called by the heartbeat job every cycle.
    Failed tasks are never retried automatically; they surface to Remy via heartbeat.
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self._db = db
        # task_id → live asyncio.Task (in-memory only; persisted state is in SQLite)
        self._active: dict[str, asyncio.Task] = {}

    @property
    def max_workers(self) -> int:
        return int(getattr(settings, "subagent_max_workers", 5))

    @property
    def max_depth(self) -> int:
        return int(getattr(settings, "subagent_max_depth", 2))

    @property
    def max_children(self) -> int:
        return int(getattr(settings, "subagent_max_children", 3))

    @property
    def stall_minutes(self) -> int:
        return int(getattr(settings, "subagent_stall_minutes", 30))

    async def spawn(
        self,
        worker_type: str,
        task_context: dict,
        parent_id: str | None = None,
        depth: int = 0,
    ) -> str:
        """
        Spawn a new worker task. Returns task_id (UUID string).

        Raises ValueError if:
        - depth >= max_depth
        - active worker count >= max_workers
        - parent already has max_children children
        """
        if depth >= self.max_depth:
            raise ValueError(
                f"Cannot spawn at depth {depth}: max_depth is {self.max_depth}"
            )
        if len(self._active) >= self.max_workers:
            raise ValueError(
                f"Worker pool full ({len(self._active)}/{self.max_workers} active)"
            )
        if parent_id is not None:
            child_count = await self._count_children(parent_id)
            if child_count >= self.max_children:
                raise ValueError(
                    f"Parent {parent_id} already has {child_count} children "
                    f"(max {self.max_children})"
                )

        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO agent_tasks
                    (task_id, parent_id, worker_type, status, task_context,
                     depth, created_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    task_id,
                    parent_id,
                    worker_type,
                    json.dumps(task_context),
                    depth,
                    now,
                ),
            )
            await conn.commit()

        asyncio_task = asyncio.create_task(
            self._run_worker(task_id, worker_type, task_context, depth),
            name=f"worker-{worker_type}-{task_id[:8]}",
        )
        self._active[task_id] = asyncio_task
        asyncio_task.add_done_callback(lambda _: self._active.pop(task_id, None))

        logger.info(
            "Spawned %s worker task_id=%s depth=%d", worker_type, task_id, depth
        )
        return task_id

    async def _run_worker(
        self,
        task_id: str,
        worker_type: str,
        task_context: dict,
        depth: int,
    ) -> None:
        """Run the worker coroutine, persisting all status transitions."""
        now_running = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE agent_tasks SET status='running', started_at=? WHERE task_id=?",
                (now_running, task_id),
            )
            await conn.commit()

        try:
            from ..skills.loader import load_skill

            skill_context = load_skill(worker_type)
            worker = _make_worker(worker_type, self._db, self)
            result = await worker.run(task_id, task_context, skill_context=skill_context)

            now_done = datetime.now(timezone.utc).isoformat()
            async with self._db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE agent_tasks
                       SET status='done', result=?, completed_at=?
                     WHERE task_id=?
                    """,
                    (result, now_done, task_id),
                )
                await conn.commit()
            logger.info("Worker %s task_id=%s done", worker_type, task_id)

        except Exception as exc:
            now_failed = datetime.now(timezone.utc).isoformat()
            async with self._db.get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE agent_tasks
                       SET status='failed', error=?, completed_at=?,
                           retry_count=retry_count+1
                     WHERE task_id=?
                    """,
                    (str(exc), now_failed, task_id),
                )
                await conn.commit()
            logger.error(
                "Worker %s task_id=%s failed: %s", worker_type, task_id, exc
            )

    async def _count_children(self, parent_id: str) -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM agent_tasks WHERE parent_id=?",
                (parent_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def check_stalled(self) -> list[str]:
        """
        Mark running tasks as stalled if they exceed the stall threshold.
        Returns the list of task_ids newly marked stalled.
        Called by the heartbeat job.
        """
        stalled_ids: list[str] = []
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT task_id FROM agent_tasks
                 WHERE status = 'running'
                   AND started_at <= datetime('now', ? || ' minutes')
                """,
                (f"-{self.stall_minutes}",),
            )
            rows = await cursor.fetchall()
            for row in rows:
                tid = row[0]
                await conn.execute(
                    "UPDATE agent_tasks SET status='stalled' WHERE task_id=?",
                    (tid,),
                )
                stalled_ids.append(tid)
            if stalled_ids:
                await conn.commit()

        if stalled_ids:
            logger.warning(
                "Marked %d task(s) stalled: %s", len(stalled_ids), stalled_ids
            )
        return stalled_ids

    @property
    def active_count(self) -> int:
        """Number of currently running asyncio tasks."""
        return len(self._active)


def _make_worker(
    worker_type: str,
    db: "DatabaseManager",
    runner: "TaskRunner",
):
    """Factory: return the correct worker instance for a given worker_type."""
    if worker_type == "research":
        from .workers.research import ResearchAgent

        return ResearchAgent(db=db, runner=runner)
    if worker_type == "goal":
        from .workers.goal import GoalWorker

        return GoalWorker(db=db)
    if worker_type == "code":
        from .workers.code import CodeAgent

        return CodeAgent(db=db)
    raise ValueError(f"Unknown worker_type: {worker_type!r}")
