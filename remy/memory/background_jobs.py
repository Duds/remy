"""
BackgroundJobStore — SQLite-backed registry for background task jobs.

Tracks the lifecycle of fire-and-forget tasks (board, retrospective, research)
so results survive bot restarts and remain queryable via /jobs or natural language.

Lifecycle:
    create()       → status='queued'  (before asyncio.create_task)
    set_running()  → status='running' (at start of BackgroundTaskRunner.run)
    set_done()     → status='done'    (on successful completion)
    set_failed()   → status='failed'  (on exception or crash recovery)

Crash recovery:
    mark_interrupted() flips any 'running' rows to 'failed' on startup,
    ensuring stale jobs are never left in a phantom 'running' state.
"""

from __future__ import annotations

import logging

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class BackgroundJobStore:
    """CRUD store for background_jobs table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def create(
        self,
        user_id: int,
        job_type: str,
        input_text: str = "",
        idempotency_key: str | None = None,
    ) -> int:
        """Insert a new job with status 'queued'. Returns the new job ID.

        If ``idempotency_key`` is given and a row with that key already exists,
        the existing job ID is returned without creating a duplicate.  This
        prevents double-execution when the scheduler fires on a crash-restart.
        """
        if idempotency_key:
            # Check for existing row first
            async with self._db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT id FROM background_jobs WHERE idempotency_key=?",
                    (idempotency_key,),
                )
                existing = await cursor.fetchone()
            if existing:
                logger.debug(
                    "Skipping duplicate background_job (idempotency_key=%s, id=%d)",
                    idempotency_key,
                    existing[0],
                )
                return int(existing[0])

        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO background_jobs (user_id, job_type, status, input_text, idempotency_key)
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (user_id, job_type, input_text, idempotency_key),
            )
            await conn.commit()
            rid = cursor.lastrowid
            if rid is None:
                raise RuntimeError(
                    "INSERT into background_jobs did not return lastrowid"
                )
            return rid

    async def set_running(self, job_id: int) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE background_jobs SET status='running' WHERE id=?",
                (job_id,),
            )
            await conn.commit()

    async def set_done(self, job_id: int, result_text: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE background_jobs
                SET status='done', result_text=?, completed_at=datetime('now')
                WHERE id=?
                """,
                (result_text, job_id),
            )
            await conn.commit()

    async def set_failed(self, job_id: int, reason: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE background_jobs
                SET status='failed', result_text=?, completed_at=datetime('now')
                WHERE id=?
                """,
                (reason, job_id),
            )
            await conn.commit()

    async def mark_interrupted(self) -> None:
        """
        Flip any jobs still marked 'running' to 'failed' with a restart note.
        Call once at startup before accepting new requests.
        """
        async with self._db.get_connection() as conn:
            result = await conn.execute(
                """
                UPDATE background_jobs
                SET status='failed',
                    result_text='interrupted by restart',
                    completed_at=datetime('now')
                WHERE status='running'
                """
            )
            await conn.commit()
            if result.rowcount:
                logger.warning(
                    "Marked %d interrupted background job(s) as failed", result.rowcount
                )

    async def list_recent(self, user_id: int, limit: int = 10) -> list[dict]:
        """Return the N most recent jobs for a user, newest first."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, job_type, status, input_text, result_text,
                       created_at, completed_at
                FROM background_jobs
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get(self, job_id: int) -> dict | None:
        """Fetch a single job by ID. Returns None if not found."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, job_type, status, input_text, result_text,
                       created_at, completed_at
                FROM background_jobs WHERE id=?
                """,
                (job_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
