"""
PlanStore — CRUD for multi-step plans with attempt tracking.

Plans are structured goals with ordered steps. Each step can have multiple
attempts logged (e.g. "called mechanic — no answer — try again Thursday").

This supports the ADHD body-double use case where tasks span days/weeks and
individual actions may need to be retried.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class PlanStore:
    """Persistent store for user plans, steps, and attempt history."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def create_plan(
        self,
        user_id: int,
        title: str,
        description: str | None = None,
        steps: list[str] | None = None,
    ) -> int:
        """Create a new plan with optional initial steps. Returns the plan ID."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO plans (user_id, title, description, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (user_id, title, description, now, now),
            )
            plan_id = cursor.lastrowid

            if steps:
                for position, step_title in enumerate(steps, start=1):
                    await conn.execute(
                        """
                        INSERT INTO plan_steps (plan_id, position, title, status, created_at, updated_at)
                        VALUES (?, ?, ?, 'pending', ?, ?)
                        """,
                        (plan_id, position, step_title, now, now),
                    )

            await conn.commit()
            logger.info("Created plan %d with %d steps for user %d", plan_id, len(steps or []), user_id)
            return plan_id

    async def add_step(
        self,
        plan_id: int,
        title: str,
        notes: str | None = None,
        position: int | None = None,
    ) -> int:
        """Add a step to an existing plan. Returns the step ID.
        
        If position is not specified, appends to the end.
        """
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            if position is None:
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM plan_steps WHERE plan_id = ?",
                    (plan_id,),
                )
                row = await cursor.fetchone()
                position = row[0]

            cursor = await conn.execute(
                """
                INSERT INTO plan_steps (plan_id, position, title, notes, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (plan_id, position, title, notes, now, now),
            )
            step_id = cursor.lastrowid

            await conn.execute(
                "UPDATE plans SET updated_at = ? WHERE id = ?",
                (now, plan_id),
            )
            await conn.commit()
            return step_id

    async def update_step_status(
        self,
        step_id: int,
        status: str,
    ) -> bool:
        """Update the status of a step. Returns True if updated."""
        valid_statuses = {"pending", "in_progress", "done", "skipped", "blocked"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        now = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE plan_steps SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, step_id),
            )
            if cursor.rowcount == 0:
                return False

            cursor = await conn.execute(
                "SELECT plan_id FROM plan_steps WHERE id = ?",
                (step_id,),
            )
            row = await cursor.fetchone()
            if row:
                await conn.execute(
                    "UPDATE plans SET updated_at = ? WHERE id = ?",
                    (now, row["plan_id"]),
                )

            await conn.commit()
            return True

    async def update_step_notes(self, step_id: int, notes: str) -> bool:
        """Update the notes on a step. Returns True if updated."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE plan_steps SET notes = ?, updated_at = ? WHERE id = ?",
                (notes, now, step_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def add_attempt(
        self,
        step_id: int,
        outcome: str,
        notes: str | None = None,
    ) -> int:
        """Log an attempt on a step. Returns the attempt ID."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO plan_step_attempts (step_id, attempted_at, outcome, notes)
                VALUES (?, ?, ?, ?)
                """,
                (step_id, now, outcome, notes),
            )
            attempt_id = cursor.lastrowid

            await conn.execute(
                "UPDATE plan_steps SET updated_at = ? WHERE id = ?",
                (now, step_id),
            )

            cursor = await conn.execute(
                "SELECT plan_id FROM plan_steps WHERE id = ?",
                (step_id,),
            )
            row = await cursor.fetchone()
            if row:
                await conn.execute(
                    "UPDATE plans SET updated_at = ? WHERE id = ?",
                    (now, row["plan_id"]),
                )

            await conn.commit()
            return attempt_id

    async def get_plan(self, plan_id: int) -> dict[str, Any] | None:
        """Get a plan with all its steps and attempt history."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, user_id, title, description, status, created_at, updated_at
                FROM plans WHERE id = ?
                """,
                (plan_id,),
            )
            plan_row = await cursor.fetchone()
            if not plan_row:
                return None

            plan = dict(plan_row)

            cursor = await conn.execute(
                """
                SELECT id, position, title, notes, status, created_at, updated_at
                FROM plan_steps WHERE plan_id = ? ORDER BY position
                """,
                (plan_id,),
            )
            step_rows = await cursor.fetchall()

            steps = []
            for step_row in step_rows:
                step = dict(step_row)

                cursor = await conn.execute(
                    """
                    SELECT id, attempted_at, outcome, notes
                    FROM plan_step_attempts WHERE step_id = ? ORDER BY attempted_at
                    """,
                    (step["id"],),
                )
                attempt_rows = await cursor.fetchall()
                step["attempts"] = [dict(a) for a in attempt_rows]
                steps.append(step)

            plan["steps"] = steps
            return plan

    async def get_plan_by_title(self, user_id: int, title: str) -> dict[str, Any] | None:
        """Find a plan by fuzzy title match. Returns the first match."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id FROM plans 
                WHERE user_id = ? AND LOWER(title) LIKE ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id, f"%{title.lower()}%"),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return await self.get_plan(row["id"])

    async def list_plans(
        self,
        user_id: int,
        status: str = "active",
    ) -> list[dict[str, Any]]:
        """List plans for a user with step progress summary.
        
        status can be: 'active', 'complete', 'abandoned', or 'all'
        """
        async with self._db.get_connection() as conn:
            if status == "all":
                cursor = await conn.execute(
                    """
                    SELECT id, title, description, status, created_at, updated_at
                    FROM plans WHERE user_id = ? ORDER BY updated_at DESC
                    """,
                    (user_id,),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT id, title, description, status, created_at, updated_at
                    FROM plans WHERE user_id = ? AND status = ? ORDER BY updated_at DESC
                    """,
                    (user_id, status),
                )
            plan_rows = await cursor.fetchall()

            plans = []
            for plan_row in plan_rows:
                plan = dict(plan_row)

                cursor = await conn.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM plan_steps WHERE plan_id = ? GROUP BY status
                    """,
                    (plan["id"],),
                )
                status_rows = await cursor.fetchall()
                step_counts = {r["status"]: r["count"] for r in status_rows}
                plan["step_counts"] = step_counts
                plan["total_steps"] = sum(step_counts.values())

                plans.append(plan)

            return plans

    async def update_plan_status(self, plan_id: int, status: str) -> bool:
        """Update the overall plan status. Returns True if updated."""
        valid_statuses = {"active", "complete", "abandoned"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        now = datetime.now(timezone.utc).isoformat()
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE plans SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, plan_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def stale_steps(
        self,
        user_id: int,
        days: int = 7,
    ) -> list[dict[str, Any]]:
        """Find steps that have been pending/in_progress for too long without activity.
        
        Returns steps from active plans where updated_at is older than `days` days.
        """
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT 
                    ps.id as step_id,
                    ps.title as step_title,
                    ps.status as step_status,
                    ps.updated_at as step_updated_at,
                    p.id as plan_id,
                    p.title as plan_title
                FROM plan_steps ps
                JOIN plans p ON ps.plan_id = p.id
                WHERE p.user_id = ?
                  AND p.status = 'active'
                  AND ps.status IN ('pending', 'in_progress')
                  AND datetime(ps.updated_at) < datetime('now', ?)
                ORDER BY ps.updated_at ASC
                """,
                (user_id, f"-{days} days"),
            )
            rows = await cursor.fetchall()

            results = []
            for row in rows:
                result = dict(row)
                cursor = await conn.execute(
                    """
                    SELECT attempted_at, outcome FROM plan_step_attempts
                    WHERE step_id = ? ORDER BY attempted_at DESC LIMIT 1
                    """,
                    (row["step_id"],),
                )
                last_attempt = await cursor.fetchone()
                if last_attempt:
                    result["last_attempt_at"] = last_attempt["attempted_at"]
                    result["last_attempt_outcome"] = last_attempt["outcome"]
                results.append(result)

            return results

    async def delete_plan(self, user_id: int, plan_id: int) -> bool:
        """Delete a plan and all its steps/attempts. Returns True if deleted."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id FROM plans WHERE id = ? AND user_id = ?",
                (plan_id, user_id),
            )
            if not await cursor.fetchone():
                return False

            await conn.execute(
                """
                DELETE FROM plan_step_attempts WHERE step_id IN (
                    SELECT id FROM plan_steps WHERE plan_id = ?
                )
                """,
                (plan_id,),
            )
            await conn.execute("DELETE FROM plan_steps WHERE plan_id = ?", (plan_id,))
            await conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
            await conn.commit()
            return True
