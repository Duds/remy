"""Claude Code CLI tool — run coding tasks via subprocess (SAD v7 P2).

Autonomous execution: Remy can dispatch a task to the Claude Code CLI and get
stdout/stderr/exit_code back without human in the loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ...config import settings

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_run_claude_code(
    registry: "ToolRegistry",
    tool_input: dict,
    user_id: int,
) -> str:
    """Run the Claude Code CLI with the given task and context; return stdout, stderr, exit_code."""
    task = (tool_input.get("task") or "").strip()
    context = (tool_input.get("context") or "").strip()
    repo_path = (tool_input.get("repo_path") or "").strip()

    if not task:
        return "Please provide a 'task' describing what you want Claude Code to do (e.g. 'Fix the bug in src/foo.py')."

    claude_path = getattr(settings, "claude_desktop_cli_path", "claude") or "claude"
    prompt_parts = [f"Task: {task}"]
    if context:
        prompt_parts.append(f"\nContext:\n{context}")
    if repo_path:
        prompt_parts.append(f"\nWork in this directory: {repo_path}")
    prompt = "\n".join(prompt_parts)

    args = [claude_path, "--print", "--no-ansi"]
    cwd = repo_path if repo_path else None

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except FileNotFoundError:
        logger.warning("Claude Code CLI not found at %s", claude_path)
        return (
            f"Claude Code CLI not found (tried: {claude_path}). "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=300.0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "Claude Code run timed out after 5 minutes."

    stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()
    exit_code = proc.returncode or 0

    lines = [f"Exit code: {exit_code}"]
    if stdout_str:
        lines.append(f"\nStdout:\n{stdout_str[:15000]}")
    if stderr_str:
        lines.append(f"\nStderr:\n{stderr_str[:2000]}")
    return "\n".join(lines)
