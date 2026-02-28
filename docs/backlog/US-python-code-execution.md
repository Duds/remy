# User Story: Python Code Writing & Execution

## Summary
As a user, I want to ask Remy to write and run Python snippets so that I can get quick
calculations, data transformations, and scripting tasks done without leaving Telegram.

---

## Background

Remy can already call external tools (web search, calendar, Gmail) but has no way to run
arbitrary computations. Many useful tasks — number crunching, string manipulation, CSV
parsing, date arithmetic — are more reliably handled by executing code than by asking the
LLM to reason through them step by step.

This feature is implemented in **three phases**:

1. **Phase A — Subprocess sandbox** (MVP): Best-effort isolation using `subprocess` with
   import blocking. Suitable for single-user deployment.
2. **Phase B — Container isolation**: Docker-based execution for proper security boundaries.
   Required before opening to untrusted users.
3. **Phase C — Jupyter-style notebooks**: Persistent kernel sessions with state preservation,
   rich output (plots, dataframes), and conversation-scoped execution contexts.

The tool is added to the existing tool registry and is available to the `quick-assistant`
path; the `board-analyst` subagent does **not** get it (read-only).

---

## Acceptance Criteria

1. **Remy writes code when asked.** Prompts like "calculate the compound interest on $5 000
   at 7% for 10 years" or "parse this CSV and sum column B" cause Remy to emit a Python
   snippet and execute it via the `run_python` tool.
2. **stdout is returned to the user.** Output up to 4 KB is included in Remy's reply.
   Larger output is truncated with a note.
3. **Execution is time-limited.** Scripts that run longer than 10 s are killed and the user
   receives a timeout message.
4. **Execution is isolated.** Each call runs in a fresh `tempfile.TemporaryDirectory`; no
   files persist between calls.
5. **Network access is disabled.** The subprocess environment has `no_proxy=*` and socket
   operations should fail (best-effort on macOS without a full sandbox).
6. **Dangerous imports are blocked.** `os.system`, `subprocess`, `shutil.rmtree`, and
   `importlib` calls raise `PermissionError` via a site-customise hook injected at startup.
7. **stderr is captured.** If the script raises an exception, the traceback is included in
   the reply so the user (and Claude) can debug.
8. **The tool is visible in `/tools`** (or equivalent tool-list command) with a one-line
   description.

---

## Implementation

**New file:** `remy/tools/run_python.py`
**Modified file:** `remy/tools/__init__.py` — register `run_python`

### `remy/tools/run_python.py`

```python
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 4096

# Injected at the top of every user script to block dangerous builtins
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

    for _attr in _BLOCKED:
        if hasattr(_os, _attr):
            setattr(_os, _attr, lambda *a, **k: (_ for _ in ()).throw(
                PermissionError(f"os.{_attr} is blocked in sandbox")))
""")


def run_python(code: str) -> str:
    """
    Execute a Python snippet in an isolated subprocess and return its output.

    Args:
        code: Python source code to execute.

    Returns:
        Combined stdout/stderr (truncated to 4 KB) or an error description.
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
            output = output[:MAX_OUTPUT_BYTES] + f"\n… (truncated at {MAX_OUTPUT_BYTES} bytes)"

        return output or "(no output)"
```

### Tool schema (for Claude tool registry)

```python
RUN_PYTHON_TOOL = {
    "name": "run_python",
    "description": (
        "Write and execute a Python 3 snippet in a sandboxed subprocess. "
        "Returns stdout + stderr (max 4 KB). No network, no persistent files, "
        "10 s time limit. Use for calculations, data transformations, and "
        "scripting tasks where reasoning alone is unreliable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            }
        },
        "required": ["code"],
    },
}
```

---

## Test Cases

| Scenario | Expected |
|---|---|
| "What is 2 ** 32?" | Executes `print(2**32)`, returns `4294967296` |
| Script exceeds 10 s (infinite loop) | Killed; user receives timeout message |
| Script imports `subprocess` | `PermissionError` in output; no crash |
| Script prints > 4 KB | Output truncated with note |
| Script raises `ZeroDivisionError` | Traceback included in reply |
| Script writes a file to `tmpdir` | File disappears when `TemporaryDirectory` closes |

---

## Security Notes

- This is a **best-effort** sandbox on macOS; it is not a full container boundary. Suitable
  for a single-user personal bot (remy's threat model) but not for multi-tenant deployments.
- If the bot is ever opened to untrusted users, replace the subprocess approach with a
  proper sandbox (e.g., `pyodide` in a WASM runtime, or a Docker-in-Docker ephemeral container).
- The `board-analyst` subagent (when implemented) must **not** receive this tool to preserve
  its read-only invariant.

---

## Out of Scope

- Installing third-party packages at runtime (`pip install` inside the sandbox)
- Persistent state between calls (each call is stateless by design)
- Interactive REPL sessions
- File uploads/downloads from Telegram linked to script execution
