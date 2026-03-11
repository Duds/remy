#!/usr/bin/env python3
"""
Step through a complex sequence of agent and tool calls in real time.

Runs one user message through ClaudeClient.stream_with_tools() with a real
ToolRegistry and prints every event (text chunks, tool status, tool results,
hand-off) so you can verify the agent loop and tool dispatch order.

Usage (from repo root):
    PYTHONPATH=. python3 scripts/trace_agent_sequence.py
    PYTHONPATH=. python3 scripts/trace_agent_sequence.py "What time is it? Then list my goals."

Requirements:
    - ANTHROPIC_API_KEY in .env (or environment)
    - Optional: data/remy.db and goals for get_goals; otherwise use a prompt
      that only triggers get_current_time (e.g. "What's the current date and time?")
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Repo root on path so "remy" and "scripts" both work
_repo = Path(__file__).resolve().parent.parent
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

# Load env before importing remy (settings read on import)
from dotenv import load_dotenv

load_dotenv(_repo / ".env")


async def main() -> None:
    from remy.ai.claude_client import (
        ClaudeClient,
        HandOffToSubAgent,
        TextChunk,
        ToolResultChunk,
        ToolStatusChunk,
        ToolTurnComplete,
    )
    from remy.ai.tools import ToolRegistry
    from remy.config import settings

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. Set it in .env or environment.")
        sys.exit(1)

    # Minimal registry (goal_store etc. None). get_current_time works; get_goals may return an error string.
    from remy.ai.tools.context import ToolContext

    ctx = ToolContext(logs_dir=str(_repo / "logs"))
    registry = ToolRegistry(ctx)

    client = ClaudeClient()
    prompt = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "What is the current date and time in my timezone? Reply in one sentence."
    )
    user_id = 1

    messages = [{"role": "user", "content": prompt}]
    print("--- Trace: agent + tool sequence ---")
    print(f"Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"Max iterations: {settings.anthropic_max_tool_iterations}")
    print()

    step = 0
    iteration = 0
    try:
        async for event in client.stream_with_tools(
            messages=messages,
            tool_registry=registry,
            user_id=user_id,
        ):
            step += 1
            if isinstance(event, TextChunk):
                print(
                    f"  [{step}] TextChunk: {event.text[:60]!r}{'...' if len(event.text) > 60 else ''}"
                )
            elif isinstance(event, ToolStatusChunk):
                iteration += 1
                print(
                    f"  [{step}] ToolStatusChunk: tool={event.tool_name!r} id={event.tool_use_id!r}"
                )
            elif isinstance(event, ToolResultChunk):
                print(
                    f"  [{step}] ToolResultChunk: tool={event.tool_name!r} result={event.result[:80]!r}{'...' if len(event.result) > 80 else ''}"
                )
            elif isinstance(event, ToolTurnComplete):
                print(
                    f"  [{step}] ToolTurnComplete: {len(event.assistant_blocks)} assistant blocks, {len(event.tool_result_blocks)} result blocks"
                )
            elif isinstance(event, HandOffToSubAgent):
                print(f"  [{step}] HandOffToSubAgent: topic={event.topic!r}")
            else:
                print(f"  [{step}] {type(event).__name__}")

        print()
        print(f"--- Done. Total events: {step}, tool turns: {iteration} ---")
    except KeyboardInterrupt:
        print("\n--- Interrupted ---")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
