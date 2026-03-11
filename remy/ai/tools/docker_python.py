"""
Docker-based Python execution (Phase B — container isolation).

Runs user code in an ephemeral container with no network, read-only root,
memory/CPU limits. Falls back to Phase A subprocess when Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DOCKER_IMAGE = "remy-python-sandbox:latest"
TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 8192
MEMORY_LIMIT = "256m"
CPU_LIMIT = "1"


def is_docker_available() -> bool:
    """True if Docker daemon is reachable and the sandbox image exists."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False


async def run_python_docker(code: str) -> str:
    """
    Execute Python code in an isolated Docker container.

    Security: --network=none, --read-only, memory/CPU limits, --cap-drop=ALL,
    non-root user. /workspace is the only writable path (temp dir mount).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        script = Path(tmpdir) / "script.py"
        script.write_text(code)

        cmd = [
            "docker",
            "run",
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
            await proc.wait()
            return f"[Timeout] Script exceeded {TIMEOUT_SECONDS} s and was killed."

        output = (stdout.decode() + stderr.decode()) or "(no output)"
        if len(output) > MAX_OUTPUT_BYTES:
            output = (
                output[:MAX_OUTPUT_BYTES]
                + f"\n… (truncated at {MAX_OUTPUT_BYTES} bytes)"
            )
        return output
