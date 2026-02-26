"""
Claude Code subprocess runner.
Spawns `claude --print --no-ansi` and streams stdout back as text chunks.
Used for complex coding/file tasks where Claude Code's agentic loop is needed.
"""

import asyncio
import logging
import signal
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class ClaudeCodeRunner:
    """Runs `claude` CLI as a subprocess and streams its output."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None

    async def run(self, prompt: str, model: str | None = None) -> AsyncIterator[str]:
        """
        Spawn `claude --print --no-ansi` with the given prompt.
        Yields text chunks from stdout as they arrive.
        """
        args = ["claude", "--print", "--no-ansi"]
        if model:
            args += ["--model", model]

        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("`claude` CLI not found. Is claude-code installed?")
            yield "[ERROR] `claude` CLI not found. Run `npm install -g @anthropic-ai/claude-code`."
            return

        # Send prompt via stdin
        if self._process.stdin:
            self._process.stdin.write(prompt.encode())
            self._process.stdin.close()

        assert self._process.stdout is not None

        buffer = ""
        try:
            while True:
                chunk = await self._process.stdout.read(256)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                buffer += text
                # Yield complete words/lines to avoid mid-word edits
                if " " in buffer or "\n" in buffer:
                    yield buffer
                    buffer = ""
        except asyncio.CancelledError:
            await self.cancel()
            raise

        if buffer:
            yield buffer

        await self._process.wait()
        if self._process.returncode not in (0, -signal.SIGTERM):
            if self._process.stderr:
                err = await self._process.stderr.read()
                if err:
                    yield f"\n[Claude Code error: {err.decode('utf-8', errors='replace').strip()}]"

        self._process = None

    async def cancel(self) -> None:
        """Send SIGTERM to the running subprocess."""
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            logger.info("Claude Code process cancelled")
        self._process = None
