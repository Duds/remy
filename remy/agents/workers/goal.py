"""Goal worker — executes a single step from a goal plan (SAD v10 §11.4).

Reads goal and step context from Remy's SQLite memory layer.
Blocks on external actions (waiting for Dale) — surfaces via heartbeat as stalled.

Input task_context keys:
  step_id  (int, required)  — plan_steps.id to execute
  goal_id  (int, optional)  — goals.id for context
  plan_id  (int, optional)  — plans.id for context

Output: JSON string {step_id, result, status}
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ...config import settings

if TYPE_CHECKING:
    from ...memory.database import DatabaseManager

logger = logging.getLogger(__name__)


class GoalWorker:
    """
    Executes a single step from a goal plan and records the outcome.

    If the step requires external action from Dale, the result will describe
    the blocker explicitly — the heartbeat will surface it as stalled.
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self._db = db

    async def run(
        self,
        task_id: str,
        task_context: dict,
        skill_context: str = "",
    ) -> str:
        step_id = task_context.get("step_id")
        goal_id = task_context.get("goal_id")

        if not step_id:
            return json.dumps(
                {"error": "No step_id provided", "status": "failed"}
            )

        step = await self._load_step(int(step_id))
        if not step:
            return json.dumps(
                {"error": f"Step {step_id} not found", "status": "failed"}
            )

        goal = await self._load_goal(int(goal_id)) if goal_id else None
        logger.info(
            "GoalWorker task_id=%s step_id=%s", task_id, step_id
        )

        model = getattr(settings, "subagent_worker_model", "mistral")
        system_prompt = (
            skill_context.strip()
            if skill_context
            else "You are a goal execution assistant. Be concise and actionable."
        )
        user_prompt = (
            f"Goal: {goal['title'] if goal else 'Unknown'}\n"
            f"Step to execute: {step['title']}\n"
            f"Notes: {step.get('notes') or 'None'}\n\n"
            "Describe the result of executing this step. "
            "If the step requires external action from the user (Dale), "
            "state it clearly as a BLOCKER: <what is needed>."
        )

        output = await _call_mistral(system_prompt, user_prompt, model)

        # Record the attempt and update step status
        await self._record_attempt(int(step_id), output)

        return json.dumps(
            {"step_id": int(step_id), "result": output, "status": "done"}
        )

    async def _load_step(self, step_id: int) -> dict | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id, plan_id, title, notes, status FROM plan_steps WHERE id=?",
                (step_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "plan_id": row[1],
            "title": row[2],
            "notes": row[3],
            "status": row[4],
        }

    async def _load_goal(self, goal_id: int) -> dict | None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT id, title, description, status FROM goals WHERE id=?",
                (goal_id,),
            )
            row = await cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "status": row[3],
        }

    async def _record_attempt(self, step_id: int, result: str) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "INSERT INTO plan_step_attempts (step_id, outcome) VALUES (?, ?)",
                (step_id, result[:1000]),
            )
            await conn.execute(
                "UPDATE plan_steps SET status='done', updated_at=datetime('now') WHERE id=?",
                (step_id,),
            )
            await conn.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _call_mistral(system: str, user: str, model: str) -> str:
    """Collect a streaming Mistral response into a single string."""
    from ...ai.mistral_client import MistralClient

    client = MistralClient()
    chunks: list[str] = []
    async for chunk in client.stream_chat(
        messages=[{"role": "user", "content": f"{system}\n\n{user}"}],
        model=model,
        max_tokens=2048,
    ):
        chunks.append(chunk)
    return "".join(chunks)
