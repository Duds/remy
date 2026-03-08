"""Code worker — wraps exec_run_claude_code subprocess (SAD v10 §11.4).

This is the one legitimate subprocess exception in the concurrency model.
All other workers use asyncio.create_task(); this one shells out to the Claude
Code CLI because it requires a proper subprocess with stdin/stdout.

Input task_context keys:
  task      (str, required) — what to build / fix / review
  context   (str, optional) — background context for the task
  repo_path (str, optional) — repository directory to work in

Output: JSON string {task, exit_code, stdout, stderr}
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...memory.database import DatabaseManager

logger = logging.getLogger(__name__)


class CodeAgent:
    """
    Thin wrapper around remy/ai/tools/claude_code.py.

    Passes task + context + repo_path to the Claude Code CLI subprocess and
    returns structured JSON so the orchestrator can synthesise the result.
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self._db = db

    async def run(
        self,
        task_id: str,
        task_context: dict,
        skill_context: str = "",
    ) -> str:
        task = (task_context.get("task") or "").strip()
        if not task:
            return json.dumps({"error": "No 'task' provided", "exit_code": 1})

        logger.info("CodeAgent task_id=%s task=%r", task_id, task[:80])

        from ...ai.tools.claude_code import exec_run_claude_code

        # exec_run_claude_code does not use the registry argument
        raw = await exec_run_claude_code(
            registry=None,  # type: ignore[arg-type]
            tool_input=task_context,
            user_id=0,  # system user — no Telegram user in context
        )

        return _parse_claude_code_output(task, raw)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_claude_code_output(task: str, raw: str) -> str:
    """Parse the formatted string from exec_run_claude_code into structured JSON."""
    exit_code = 0
    stdout = ""
    stderr = ""

    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Exit code:"):
            try:
                exit_code = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("Stdout:"):
            # Everything after "Stdout:\n" until "Stderr:\n" or end
            rest = "\n".join(lines[i + 1 :])
            if "Stderr:" in rest:
                stdout = rest.split("Stderr:", 1)[0].strip()
            else:
                stdout = rest.strip()
        elif line.startswith("Stderr:"):
            stderr = "\n".join(lines[i + 1 :]).strip()

    return json.dumps(
        {
            "task": task,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        }
    )
