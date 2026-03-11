"""
Subagent runner — runs a sub-agent from a spec with filtered tools.

Consumes stream_with_tools and collects the final text for delivery via
BackgroundTaskRunner (US-agent-creator, US-multi-agent-architecture).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .creator import SubAgentSpec

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient
    from ..ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class FilteredToolRegistry:
    """
    Wraps a ToolRegistry and exposes only a subset of tools.
    Used by sub-agents so they cannot call tools outside their spec.
    """

    def __init__(self, inner: "ToolRegistry", allowed_tool_names: list[str]) -> None:
        self._inner = inner
        self._allowed = set(allowed_tool_names)

    @property
    def schemas(self) -> list[dict]:
        """Return only schemas for allowed tools."""
        return [
            s for s in self._inner.schemas if s.get("name") in self._allowed
        ]

    async def dispatch(
        self,
        tool_name: str,
        tool_input: dict,
        user_id: int,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> str:
        """Dispatch only if tool is allowed; otherwise return error."""
        if tool_name not in self._allowed:
            return (
                f"Tool '{tool_name}' is not available in this sub-agent. "
                "Use only the tools you have been given."
            )
        return await self._inner.dispatch(
            tool_name, tool_input, user_id, chat_id, message_id
        )


async def run_subagent(
    spec: SubAgentSpec,
    task_description: str,
    user_id: int,
    registry: "ToolRegistry",
    claude_client: "ClaudeClient",
) -> str:
    """
    Run a sub-agent with the given spec: limited tools, system prompt, max turns.
    Consumes the tool loop and returns the final assistant text.

    Used by AgentCreator.spawn_and_hand_off when firing a background task.
    """
    from ..ai.claude_client import TextChunk, ToolStatusChunk, ToolTurnComplete

    filtered = FilteredToolRegistry(registry, spec.allowed_tools)
    messages: list[dict] = [
        {"role": "user", "content": task_description.strip() or "Proceed."}
    ]
    final_text: list[str] = []
    in_tool_turn = False

    try:
        async for event in claude_client.stream_with_tools(
            messages=messages,
            tool_registry=filtered,
            user_id=user_id,
            system=spec.system_prompt,
            max_iterations=spec.max_turns,
        ):
            if isinstance(event, TextChunk):
                if not in_tool_turn:
                    final_text.append(event.text)
            elif isinstance(event, ToolStatusChunk):
                in_tool_turn = True
            elif isinstance(event, ToolTurnComplete):
                in_tool_turn = False

        return "".join(final_text).strip() or "(No reply generated.)"
    except asyncio.TimeoutError:
        logger.warning("Subagent %s timed out for user %d", spec.type.value, user_id)
        return (
            f"The {spec.type.value} task ran out of time. "
            "You can try again with a narrower request."
        )
    except Exception as e:
        logger.exception("Subagent %s failed for user %d: %s", spec.type.value, user_id, e)
        return f"Sorry, the {spec.type.value} task failed: {e}"
