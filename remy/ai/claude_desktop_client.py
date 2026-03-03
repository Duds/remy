"""
Claude Code CLI client for subscription-first routing.

Wraps `claude -p <prompt> --output-format stream-json --verbose
--include-partial-messages` to stream responses via the user's Claude
subscription rather than the Anthropic API key.

Usage in ModelRouter: when settings.claude_desktop_enabled is True,
_stream_with_fallback("claude", ...) tries this client first, then falls
back to ClaudeClient (API) on failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from ..models import TokenUsage

logger = logging.getLogger(__name__)


def _extract_text(content: object) -> str:
    """Extract plain text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


class ClaudeDesktopClient:
    """
    Streams responses via the Claude Code CLI (`claude -p`).

    Formats the full conversation history as context within the system prompt
    and passes the latest user message as the `-p` prompt.  Parses NDJSON
    stream-json output, yielding text deltas as they arrive.

    Availability is checked once (subprocess `claude --version`) and cached
    for the lifetime of the instance.  The circuit breaker in ModelRouter
    handles runtime failures independently.
    """

    def __init__(self, cli_path: str = "claude") -> None:
        self._cli_path = cli_path
        self._available: bool | None = None  # None = not yet checked

    async def is_available(self) -> bool:
        """Return True if the Claude Code CLI is installed and reachable.

        Result is cached — subsequent calls return immediately without
        spawning a subprocess.
        """
        if self._available is None:
            self._available = await self._check()
        return self._available

    async def _check(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            ok = proc.returncode == 0
            logger.debug("ClaudeDesktopClient availability check: %s", ok)
            return ok
        except (FileNotFoundError, asyncio.TimeoutError, OSError) as e:
            logger.debug("ClaudeDesktopClient not available: %s", e)
            return False

    async def stream_message(
        self,
        messages: list[dict],
        model: str | None = None,
        system: str | None = None,
        usage_out: TokenUsage | None = None,
    ) -> AsyncIterator[str]:
        """Stream a response from the Claude Code CLI.

        Builds a system prompt from the original system string plus
        conversation history, passes the last user message as `-p`.
        Parses `stream-json` NDJSON lines and yields text deltas.

        Raises RuntimeError if the CLI binary is not found.
        """
        if not messages:
            return

        # Build combined system context
        system_parts: list[str] = []
        if system:
            system_parts.append(system)

        # All messages except the last user turn become conversation history
        history = messages[:-1] if len(messages) > 1 else []
        if history:
            lines: list[str] = []
            for msg in history:
                role = msg.get("role", "")
                text = _extract_text(msg.get("content", ""))
                if not text:
                    continue
                if role == "user":
                    lines.append(f"Human: {text}")
                elif role == "assistant":
                    lines.append(f"Assistant: {text}")
            if lines:
                system_parts.append("Conversation so far:\n" + "\n\n".join(lines))

        prompt = _extract_text(messages[-1].get("content", ""))
        if not prompt:
            return

        cmd = [
            self._cli_path,
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if system_parts:
            cmd.extend(["-s", "\n\n".join(system_parts)])

        logger.debug(
            "ClaudeDesktopClient: spawning %s -p <prompt> (system=%s)",
            self._cli_path,
            bool(system_parts),
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            self._available = False
            raise RuntimeError(f"Claude CLI not found at {self._cli_path!r}")

        last_text = ""
        try:
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")

                if etype == "assistant":
                    content_blocks = event.get("message", {}).get("content", [])
                    new_text = ""
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "text":
                            new_text += block.get("text", "")

                    # Yield the incremental delta from the last seen text
                    if new_text.startswith(last_text):
                        delta = new_text[len(last_text):]
                        if delta:
                            yield delta
                    else:
                        # Text changed in a non-additive way — yield full new text
                        if new_text:
                            yield new_text
                    last_text = new_text

                    # Capture usage from the final (non-partial) assistant event
                    if not event.get("partial") and usage_out is not None:
                        raw_usage = event.get("message", {}).get("usage", {})
                        usage_out.input_tokens = raw_usage.get("input_tokens", 0)
                        usage_out.output_tokens = raw_usage.get("output_tokens", 0)

                elif etype == "result":
                    break

        finally:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
