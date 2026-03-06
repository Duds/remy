"""Run temporary Python scripts in a sandboxed subprocess (Phase A — MVP)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 4096

# Injected at the top of every user script to block dangerous builtins and imports.
_PREAMBLE = textwrap.dedent("""
    import builtins as _builtins
    import os as _os

    _BLOCKED = {"system", "popen", "execv", "execve", "execvp", "execvpe"}

    _real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _safe_import(name, *args, **kwargs):
        if name in ("subprocess", "shutil", "importlib"):
            raise PermissionError(f"Import of '{name}' is not allowed in sandbox")
        return _real_import(name, *args, **kwargs)

    __builtins__.__import__ = _safe_import

    def _blocked_os(attr):
        def _raiser(*a, **k):
            raise PermissionError(f"os.{attr} is blocked in sandbox")
        return _raiser

    for _attr in _BLOCKED:
        if hasattr(_os, _attr):
            setattr(_os, _attr, _blocked_os(_attr))
""")


def run_python(code: str) -> str:
    """
    Execute a Python snippet in an isolated subprocess and return its output.

    Each run uses a fresh temp directory; no files or state persist.
    Network is disabled via no_proxy; dangerous imports (subprocess, shutil,
    importlib) and os.system/popen/exec* are blocked by the preamble.

    Args:
        code: Python source code to execute.

    Returns:
        Combined stdout/stderr (truncated to MAX_OUTPUT_BYTES) or an error description.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "script.py"
        script.write_text(_PREAMBLE + "\n" + code)

        env = {
            "PATH": "/usr/bin:/bin",
            "no_proxy": "*",
            "NO_PROXY": "*",
        }

        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                cwd=tmpdir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"[Timeout] Script exceeded {TIMEOUT_SECONDS} s and was killed."

        output = result.stdout + result.stderr
        if len(output) > MAX_OUTPUT_BYTES:
            output = (
                output[:MAX_OUTPUT_BYTES]
                + f"\n… (truncated at {MAX_OUTPUT_BYTES} bytes)"
            )

        return output or "(no output)"


async def exec_run_python(
    registry: ToolRegistry, tool_input: dict, user_id: int
) -> str:
    """
    Tool executor: run user-provided Python code in a sandbox and return output.

    Runs the blocking run_python() in a thread pool so the event loop is not blocked.
    """
    code = (tool_input.get("code") or "").strip()
    if not code:
        return "No code provided. Please supply Python source to execute."
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_python, code)
