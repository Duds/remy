# User Story: Remy Writes and Runs Temporary Python Scripts

**Status:** Phase A ✅ Implemented | Phase B ✅ Implemented (Docker fallback) | Phase C ⬜ Backlog

## Summary

As Dale, I want Remy to write and run temporary Python scripts on demand so that I can get calculations, graphs, and other programmatic content directly in conversation — without opening a notebook or terminal. Scripts are ephemeral by default: they run once, produce output (text or images), and leave no persistent state unless I opt into a session.

---

## Background

Remy can call external tools (web search, calendar, Gmail) but has no way to run arbitrary computations. Many useful answers — compound interest, date arithmetic, CSV summaries, a quick plot — are better delivered by running a small program than by the model reasoning step by step. I want to ask in natural language (“plot the last 7 days of step counts” or “what’s 5k at 4.2% for 3 years?”) and have Remy generate a Python snippet, run it in a safe environment, and return the result, including graphs as images and tables as formatted output.

Scripts are **temporary** by default: each run is isolated (fresh process or container), no files or variables persist, and execution is time-limited. Optional session mode (Phase C) preserves variables and rich output (matplotlib figures, DataFrames) within a conversation.

This feature is implemented in **three phases**:

1. **Phase A — Subprocess sandbox** (MVP): Best-effort isolation using `subprocess` with
   import blocking. Suitable for single-user deployment.
2. **Phase B — Container isolation**: Docker-based execution for proper security boundaries.
   Required before opening to untrusted users.
3. **Phase C — Jupyter-style notebooks**: Persistent kernel sessions with state preservation,
   rich output (plots, dataframes), and conversation-scoped execution contexts.

The tool is added to the existing tool registry and is available to the main Remy / `quick-assistant` path; the `board-analyst` subagent does **not** get it (read-only). Remy should briefly describe what she’s running (e.g. “Running a quick Python script to compute that…”) and surface errors or truncation in plain language.

---

## Acceptance Criteria

### Phase A — Subprocess Sandbox (MVP)

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

### Phase B — Container Isolation

9. **Docker-based execution.** Code runs inside an ephemeral Docker container with:
   - Read-only root filesystem
   - No network access (`--network=none`)
   - Memory limit (256 MB default)
   - CPU limit (1 core)
   - No privileged capabilities (`--cap-drop=ALL`)
   - Automatic container cleanup after execution
10. **Pre-built image with common packages.** The container image includes:
    - `numpy`, `pandas`, `matplotlib`, `scipy`
    - `requests` (disabled at runtime via network isolation)
    - `python-dateutil`, `pytz`
    - Standard library only beyond these
11. **Volume mounting for file exchange.** A temporary host directory is mounted read-write
    at `/workspace` inside the container for input/output files.
12. **Graceful fallback.** If Docker is unavailable, fall back to Phase A subprocess
    sandbox with a warning logged.
13. **Container pool (optional).** Pre-warm 2–3 containers to reduce cold-start latency
    from ~2 s to ~200 ms.

### Phase C — Jupyter-Style Notebooks

14. **Persistent kernel sessions.** Each conversation gets an optional long-lived IPython
    kernel that preserves variables between `run_python` calls within the same session.
15. **Session management commands:**
    - `/python new` — Start a fresh kernel session
    - `/python reset` — Clear all variables but keep session alive
    - `/python end` — Terminate the kernel and free resources
16. **Rich output support:**
    - Matplotlib plots rendered as PNG and sent as Telegram photos
    - Pandas DataFrames formatted as Markdown tables (≤20 rows) or truncated with summary
    - NumPy arrays pretty-printed with shape info
17. **Automatic session timeout.** Kernels idle for >30 minutes are automatically terminated
    to free resources.
18. **Session state indicator.** Remy's replies include a subtle indicator when a kernel
    session is active: `🐍 [session active, 3 vars]`
19. **Variable inspection.** User can ask "what variables do I have?" and Remy lists
    current session variables with types and shapes.
20. **History replay.** On kernel restart, Remy can optionally replay previous cells to
    restore state (user must opt-in due to potential side effects).

---

## Implementation

### Phase A — Subprocess Sandbox

**New file:** `remy/tools/run_python.py`
**Modified file:** `remy/tools/__init__.py` — register `run_python`

#### `remy/tools/run_python.py`

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

#### Tool schema (for Claude tool registry)

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

### Phase B — Container Isolation

**New file:** `remy/tools/docker_python.py`
**New file:** `docker/python-sandbox/Dockerfile`
**Modified file:** `remy/tools/run_python.py` — add Docker backend selection

#### `docker/python-sandbox/Dockerfile`

```dockerfile
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    numpy==1.26.* \
    pandas==2.1.* \
    matplotlib==3.8.* \
    scipy==1.11.* \
    python-dateutil==2.8.* \
    pytz==2024.*

RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /workspace

ENTRYPOINT ["python"]
```

#### `remy/tools/docker_python.py`

```python
import asyncio
import tempfile
from pathlib import Path

DOCKER_IMAGE = "remy-python-sandbox:latest"
TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 8192
MEMORY_LIMIT = "256m"
CPU_LIMIT = "1"


async def run_python_docker(code: str) -> str:
    """
    Execute Python code in an isolated Docker container.
    
    Security features:
    - No network access (--network=none)
    - Read-only root filesystem (--read-only)
    - Memory and CPU limits
    - All capabilities dropped
    - Non-root user inside container
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "script.py"
        script.write_text(code)
        
        cmd = [
            "docker", "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--memory", MEMORY_LIMIT,
            "--cpus", CPU_LIMIT,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "-v", f"{tmpdir}:/workspace:rw",
            "-w", "/workspace",
            DOCKER_IMAGE,
            "/workspace/script.py",
        ]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return f"[Timeout] Script exceeded {TIMEOUT_SECONDS} s and was killed."
        
        output = stdout.decode() + stderr.decode()
        if len(output) > MAX_OUTPUT_BYTES:
            output = output[:MAX_OUTPUT_BYTES] + f"\n… (truncated at {MAX_OUTPUT_BYTES} bytes)"
        
        return output or "(no output)"


def is_docker_available() -> bool:
    """Check if Docker daemon is running and image exists."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False
```

#### Container pool (optional optimisation)

```python
import asyncio
from collections import deque

class ContainerPool:
    """Pre-warmed container pool for reduced cold-start latency."""
    
    def __init__(self, size: int = 3):
        self.size = size
        self._pool: deque[str] = deque()
        self._lock = asyncio.Lock()
    
    async def warm(self):
        """Pre-create containers in paused state."""
        for _ in range(self.size):
            container_id = await self._create_paused_container()
            self._pool.append(container_id)
    
    async def acquire(self) -> str:
        """Get a pre-warmed container or create new one."""
        async with self._lock:
            if self._pool:
                return self._pool.popleft()
        return await self._create_paused_container()
    
    async def release(self, container_id: str):
        """Return container to pool or destroy if pool is full."""
        async with self._lock:
            if len(self._pool) < self.size:
                await self._reset_container(container_id)
                self._pool.append(container_id)
            else:
                await self._destroy_container(container_id)
    
    async def _create_paused_container(self) -> str:
        # Implementation: docker create + docker start --attach
        ...
    
    async def _reset_container(self, container_id: str):
        # Implementation: clear /workspace, reset environment
        ...
    
    async def _destroy_container(self, container_id: str):
        # Implementation: docker rm -f
        ...
```

---

### Phase C — Jupyter-Style Notebooks

**New file:** `remy/tools/jupyter_kernel.py`
**New file:** `remy/tools/kernel_manager.py`
**Modified file:** `remy/bot/handlers.py` — add `/python` command handler
**New dependency:** `jupyter_client` (add to `requirements.txt`)

#### `remy/tools/kernel_manager.py`

```python
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import uuid

from jupyter_client import AsyncKernelManager


@dataclass
class KernelSession:
    """Represents a persistent Python kernel session for a conversation."""
    
    session_id: str
    conversation_id: str
    kernel_manager: AsyncKernelManager
    kernel_client: any
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    cell_count: int = 0
    variables: dict = field(default_factory=dict)
    
    @property
    def idle_duration(self) -> timedelta:
        return datetime.now() - self.last_used


class KernelSessionManager:
    """Manages Jupyter kernel sessions across conversations."""
    
    IDLE_TIMEOUT = timedelta(minutes=30)
    MAX_SESSIONS = 10
    
    def __init__(self):
        self._sessions: dict[str, KernelSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the background cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop(self):
        """Stop all sessions and cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for session in list(self._sessions.values()):
            await self.end_session(session.conversation_id)
    
    async def get_or_create_session(self, conversation_id: str) -> KernelSession:
        """Get existing session or create a new one."""
        if conversation_id in self._sessions:
            session = self._sessions[conversation_id]
            session.last_used = datetime.now()
            return session
        
        # Enforce max sessions limit
        if len(self._sessions) >= self.MAX_SESSIONS:
            await self._evict_oldest_session()
        
        return await self._create_session(conversation_id)
    
    async def _create_session(self, conversation_id: str) -> KernelSession:
        """Create a new kernel session."""
        km = AsyncKernelManager(kernel_name="python3")
        await km.start_kernel()
        kc = km.client()
        kc.start_channels()
        
        session = KernelSession(
            session_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            kernel_manager=km,
            kernel_client=kc,
        )
        self._sessions[conversation_id] = session
        return session
    
    async def end_session(self, conversation_id: str) -> bool:
        """Terminate a kernel session."""
        if conversation_id not in self._sessions:
            return False
        
        session = self._sessions.pop(conversation_id)
        session.kernel_client.stop_channels()
        await session.kernel_manager.shutdown_kernel()
        return True
    
    async def reset_session(self, conversation_id: str) -> bool:
        """Clear variables but keep session alive."""
        if conversation_id not in self._sessions:
            return False
        
        session = self._sessions[conversation_id]
        await self.execute(conversation_id, "%reset -f")
        session.variables.clear()
        session.cell_count = 0
        return True
    
    async def execute(self, conversation_id: str, code: str) -> dict:
        """Execute code in a session and return results."""
        session = await self.get_or_create_session(conversation_id)
        session.last_used = datetime.now()
        session.cell_count += 1
        
        kc = session.kernel_client
        msg_id = kc.execute(code)
        
        outputs = []
        images = []
        
        while True:
            try:
                msg = await asyncio.wait_for(
                    kc.get_iopub_msg(),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                return {"error": "Execution timed out", "outputs": outputs}
            
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            
            msg_type = msg["msg_type"]
            content = msg["content"]
            
            if msg_type == "status" and content["execution_state"] == "idle":
                break
            elif msg_type == "stream":
                outputs.append(content["text"])
            elif msg_type == "execute_result":
                outputs.append(content["data"].get("text/plain", ""))
            elif msg_type == "display_data":
                if "image/png" in content["data"]:
                    images.append(content["data"]["image/png"])
                elif "text/plain" in content["data"]:
                    outputs.append(content["data"]["text/plain"])
            elif msg_type == "error":
                outputs.append("\n".join(content["traceback"]))
        
        # Update variable tracking
        await self._update_variables(session)
        
        return {
            "outputs": outputs,
            "images": images,
            "cell_number": session.cell_count,
            "variables": session.variables,
        }
    
    async def _update_variables(self, session: KernelSession):
        """Query kernel for current variable state."""
        kc = session.kernel_client
        msg_id = kc.execute(
            "import json; print(json.dumps("
            "{k: type(v).__name__ for k, v in globals().items() "
            "if not k.startswith('_')}))"
        )
        # Parse response and update session.variables
        ...
    
    async def _cleanup_loop(self):
        """Periodically clean up idle sessions."""
        while True:
            await asyncio.sleep(60)
            now = datetime.now()
            expired = [
                cid for cid, session in self._sessions.items()
                if session.idle_duration > self.IDLE_TIMEOUT
            ]
            for cid in expired:
                await self.end_session(cid)
    
    async def _evict_oldest_session(self):
        """Remove the oldest session when at capacity."""
        oldest = min(
            self._sessions.values(),
            key=lambda s: s.last_used,
        )
        await self.end_session(oldest.conversation_id)
    
    def get_session_info(self, conversation_id: str) -> Optional[dict]:
        """Get session status for display."""
        if conversation_id not in self._sessions:
            return None
        
        session = self._sessions[conversation_id]
        return {
            "active": True,
            "cell_count": session.cell_count,
            "variable_count": len(session.variables),
            "idle_seconds": int(session.idle_duration.total_seconds()),
            "variables": session.variables,
        }
```

#### Rich output formatting

```python
import base64
from typing import Optional

import pandas as pd


def format_dataframe(df: pd.DataFrame, max_rows: int = 20) -> str:
    """Format DataFrame as Markdown table with truncation."""
    if len(df) <= max_rows:
        return df.to_markdown(index=False)
    
    head = df.head(max_rows // 2)
    tail = df.tail(max_rows // 2)
    
    return (
        head.to_markdown(index=False) +
        f"\n\n... ({len(df) - max_rows} rows hidden) ...\n\n" +
        tail.to_markdown(index=False) +
        f"\n\n**Shape:** {df.shape[0]} rows × {df.shape[1]} columns"
    )


def extract_plot_image(outputs: list) -> Optional[bytes]:
    """Extract PNG image data from Jupyter outputs."""
    for output in outputs:
        if isinstance(output, dict) and "image/png" in output:
            return base64.b64decode(output["image/png"])
    return None


def format_session_indicator(session_info: Optional[dict]) -> str:
    """Format session status for message footer."""
    if not session_info:
        return ""
    
    var_count = session_info["variable_count"]
    return f"🐍 [session active, {var_count} var{'s' if var_count != 1 else ''}]"
```

#### Tool schema update for Phase C

```python
RUN_PYTHON_TOOL = {
    "name": "run_python",
    "description": (
        "Write and execute Python 3 code. In stateless mode: sandboxed subprocess, "
        "10 s limit, no persistence. In session mode: Jupyter kernel with variable "
        "persistence, matplotlib plots returned as images, pandas DataFrames as tables. "
        "Use for calculations, data analysis, and visualisation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
            "use_session": {
                "type": "boolean",
                "description": (
                    "If true, use persistent Jupyter session (variables preserved "
                    "between calls). Default: false."
                ),
                "default": False,
            },
        },
        "required": ["code"],
    },
}
```

---

## Test Cases

### User-facing (all phases)

| Scenario | Expected |
|----------|----------|
| “What is compound interest on $10k at 5% for 10 years?” | Remy runs a small Python script and replies with the numeric result. |
| “Plot a simple line graph of y = x² for x in 0..5” | When Phase C (or plot support) is available, Remy returns a plot image and short explanation. |
| No persistent state by default | Two separate messages each run a script; second run does not see first run’s variables. |

### Phase A — Subprocess Sandbox

| Scenario | Expected |
|---|---|
| "What is 2 ** 32?" | Executes `print(2**32)`, returns `4294967296` |
| Script exceeds 10 s (infinite loop) | Killed; user receives timeout message |
| Script imports `subprocess` | `PermissionError` in output; no crash |
| Script prints > 4 KB | Output truncated with note |
| Script raises `ZeroDivisionError` | Traceback included in reply |
| Script writes a file to `tmpdir` | File disappears when `TemporaryDirectory` closes |

### Phase B — Container Isolation

| Scenario | Expected |
|---|---|
| Docker available | Code runs in container with proper isolation |
| Docker unavailable | Falls back to subprocess sandbox with warning |
| Script tries network access | Fails immediately (no DNS, no sockets) |
| Script exceeds 256 MB memory | Container killed with OOM message |
| Script uses numpy/pandas | Works (pre-installed in image) |
| Script tries `pip install` | Fails (read-only filesystem) |

### Phase C — Jupyter Sessions

| Scenario | Expected |
|---|---|
| `x = 42` then `print(x)` in same session | Second cell prints `42` |
| `/python new` | Fresh kernel started, previous variables cleared |
| `/python reset` | Variables cleared, kernel stays alive |
| `/python end` | Kernel terminated, resources freed |
| `plt.plot([1,2,3])` | PNG image sent as Telegram photo |
| `pd.DataFrame(...)` | Rendered as Markdown table |
| Session idle > 30 min | Automatically terminated |
| "What variables do I have?" | Lists current session variables with types |
| 10 concurrent sessions | Oldest session evicted when 11th requested |

---

## Security Notes

### Phase A

- This is a **best-effort** sandbox on macOS; it is not a full container boundary. Suitable
  for a single-user personal bot (Remy's threat model) but not for multi-tenant deployments.
- The `board-analyst` subagent (when implemented) must **not** receive this tool to preserve
  its read-only invariant.

### Phase B

- Docker provides proper process isolation, namespace separation, and resource limits.
- The `--network=none` flag ensures no network access even if code attempts socket operations.
- The `--read-only` flag prevents filesystem modifications outside the mounted workspace.
- The `--cap-drop=ALL` flag removes all Linux capabilities, preventing privilege escalation.
- Container images should be rebuilt periodically to include security patches.

### Phase C

- Jupyter kernels run with the same privileges as the Remy process — Phase B container
  isolation should be combined with Phase C for production deployments.
- Session timeout prevents resource exhaustion from abandoned kernels.
- Variable inspection exposes variable names and types but not values (unless explicitly
  printed).
- History replay is opt-in because replaying cells with side effects (file writes, API
  calls) could cause unintended consequences.

---

## Dependencies

### Phase A
- None (standard library only)

### Phase B
- Docker installed and running on host
- `remy-python-sandbox` image built from provided Dockerfile

### Phase C
- `jupyter_client>=8.0`
- `ipykernel>=6.0`
- `pandas>=2.0` (for DataFrame formatting)
- `tabulate>=0.9` (for `to_markdown()` support)

---

## Out of Scope

- Installing third-party packages at runtime (`pip install` inside the sandbox)
- Running long-lived or production scripts; this is for ad-hoc, user-requested execution only
- Interactive REPL sessions (beyond Jupyter cell execution)
- File uploads/downloads from Telegram linked to script execution
- Multi-user kernel sharing (each conversation gets its own kernel)
- GPU/CUDA support
- Remote kernel execution (kernels run on same host as Remy)
