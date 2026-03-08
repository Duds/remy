"""Task Orchestrator — stateless coordinator for the sub-agent system (SAD v10 §11).

Injected with: task manifest + TASK.md contents at each call.
Spawns workers via TaskRunner, collects results, synthesises into structured JSON.
Never contacts Dale directly — all output goes to agent_tasks.synthesis via SQLite.

Named task_orchestrator.py (not orchestrator.py) to avoid collision with the existing
Board of Directors BoardOrchestrator in remy/agents/orchestrator.py.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic

from ..config import settings

if TYPE_CHECKING:
    from ..memory.database import DatabaseManager
    from .runner import TaskRunner

logger = logging.getLogger(__name__)

# Synthesis output schema (SAD v10 §11.8)
_SYNTHESIS_SCHEMA = '{"summary": "...", "findings": [...], "gaps": [...], "relevant_goals": [...]}'


class TaskOrchestrator:
    """
    Stateless task coordinator. Each call loads TASK.md + skill context from disk
    (hot-reloadable — no deploy needed to tune behaviour).

    State lives only in SQLite (agent_tasks table). This class holds no persistent
    state beyond the db reference and path config.
    """

    def __init__(
        self,
        db: "DatabaseManager",
        runner: "TaskRunner",
        task_md_path: str | None = None,
    ) -> None:
        self._db = db
        self._runner = runner
        self._task_md_path = task_md_path or getattr(
            settings, "task_md_path", "config/TASK.md"
        )

    def _load_task_md(self) -> str:
        """Load TASK.md, falling back to TASK.example.md if private file is absent."""
        for candidate in [self._task_md_path, "config/TASK.example.md"]:
            p = Path(candidate)
            if p.exists():
                return p.read_text(encoding="utf-8")
        return ""

    async def delegate(
        self,
        worker_type: str,
        task_context: dict,
        parent_task_id: str | None = None,
        depth: int = 0,
    ) -> str:
        """
        Delegate a task to a worker via the TaskRunner.
        Returns task_id. Workers run asynchronously; collect results with synthesise().
        """
        return await self._runner.spawn(
            worker_type=worker_type,
            task_context=task_context,
            parent_id=parent_task_id,
            depth=depth,
        )

    async def synthesise(
        self,
        parent_task_id: str,
        worker_results: list[dict],
        delegation_context: str = "",
        task_type: str = "",
    ) -> dict:
        """
        Synthesise completed worker results into structured JSON.

        worker_results: list of {task_id, worker_type, result, error}
        delegation_context: the original request Remy sent (what + why)
        task_type: used to load matching skill context (e.g. "research")

        Returns synthesis dict and persists it to agent_tasks.synthesis for parent_task_id.
        """
        task_md = self._load_task_md()

        # Load skill context for the task type
        skill_text = ""
        if task_type:
            from ..skills.loader import load_skill

            skill_text = load_skill(task_type)

        system_parts = [task_md]
        if skill_text:
            system_parts.append(skill_text)
        system_prompt = "\n\n---\n\n".join(p for p in system_parts if p).strip()
        if not system_prompt:
            system_prompt = "Synthesise worker results into structured JSON."

        results_text = _format_worker_results(worker_results)
        user_prompt = (
            f"Delegation context:\n{delegation_context}\n\n"
            f"Worker results:\n{results_text}\n\n"
            f"Produce synthesis JSON matching this schema:\n{_SYNTHESIS_SCHEMA}"
        )

        model = getattr(settings, "subagent_synth_model", "claude-sonnet-4-20250514")
        synthesis_text = await _call_claude(system_prompt, user_prompt, model)
        synthesis = _parse_synthesis(synthesis_text)

        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE agent_tasks SET synthesis=? WHERE task_id=?",
                (json.dumps(synthesis), parent_task_id),
            )
            await conn.commit()

        logger.info("Synthesised results for task %s", parent_task_id)
        return synthesis

    async def get_pending_workers(self, parent_task_id: str) -> list[dict]:
        """Return worker tasks for this parent that are still pending or running."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT task_id, worker_type, status, result, error
                  FROM agent_tasks
                 WHERE parent_id = ?
                   AND status IN ('pending', 'running')
                """,
                (parent_task_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "task_id": r[0],
                "worker_type": r[1],
                "status": r[2],
                "result": r[3],
                "error": r[4],
            }
            for r in rows
        ]

    async def get_completed_workers(self, parent_task_id: str) -> list[dict]:
        """Return worker tasks for this parent that are done or failed."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT task_id, worker_type, status, result, error
                  FROM agent_tasks
                 WHERE parent_id = ?
                   AND status IN ('done', 'failed')
                """,
                (parent_task_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "task_id": r[0],
                "worker_type": r[1],
                "status": r[2],
                "result": r[3],
                "error": r[4],
            }
            for r in rows
        ]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _format_worker_results(worker_results: list[dict]) -> str:
    parts = []
    for r in worker_results:
        header = f"Worker: {r.get('worker_type', '?')} (task_id={r.get('task_id', '?')})"
        if r.get("result"):
            parts.append(f"{header}\nResult:\n{r['result']}")
        else:
            parts.append(f"{header}\nError: {r.get('error', 'unknown')}")
    return "\n\n".join(parts) if parts else "No worker results available."


async def _call_claude(system_prompt: str, user_prompt: str, model: str) -> str:
    """Non-streaming Claude call for synthesis."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text if response.content else ""


def _parse_synthesis(text: str) -> dict:
    """Extract JSON from synthesis text; fall back gracefully if parsing fails."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return {
        "summary": text[:500] if text else "No synthesis produced.",
        "findings": [],
        "gaps": ["Synthesis JSON parsing failed — see raw summary."],
        "relevant_goals": [],
    }
