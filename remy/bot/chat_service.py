"""
Message processing service — orchestrates session, memory injection, Claude streaming, persist.

Extracts business logic from handlers so they become thin adapters. No Telegram types.
Used by TUI runner and (optionally) Telegram chat handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Awaitable, Callable
from zoneinfo import ZoneInfo

from ..bot.handlers.base import (
    _build_message_from_turn,
    _sanitize_messages_for_claude,
    _trim_messages_to_budget,
)
from ..config import settings
from ..models import ConversationTurn

if TYPE_CHECKING:
    from ..ai.claude_client import StreamEvent, TextChunk, ToolStatusChunk, ToolTurnComplete
    from ..ai.tools import ToolRegistry
    from ..memory.conversations import ConversationStore
    from ..memory.injector import MemoryInjector

logger = logging.getLogger(__name__)


@dataclass
class MessageProcessingDeps:
    """Dependencies for MessageProcessingService."""

    conv_store: "ConversationStore"
    claude_client: object  # ClaudeClient
    tool_registry: "ToolRegistry"
    memory_injector: "MemoryInjector | None"
    session_manager: object  # SessionManager
    settings: object  # Settings


class MessageProcessingService:
    """
    Orchestrates session, memory injection, Claude streaming, and persistence.
    No Telegram types — caller provides on_event callback for UI updates.
    """

    def __init__(self, deps: MessageProcessingDeps) -> None:
        self._deps = deps

    async def process_text(
        self,
        user_id: int,
        text: str,
        session_key: str,
        on_event: Callable[["StreamEvent"], Awaitable[None]],
        *,
        local_hour: int | None = None,
    ) -> None:
        """
        Run one chat turn: append user message, load history, build prompt,
        stream_with_tools, persist. Calls on_event for each stream event.
        """
        from ..ai.input_validator import sanitize_memory_injection

        conv_store = self._deps.conv_store
        session_manager = self._deps.session_manager
        claude_client = self._deps.claude_client
        tool_registry = self._deps.tool_registry
        memory_injector = self._deps.memory_injector
        limit = settings.compaction_keep_recent_messages

        user_turn = ConversationTurn(role="user", content=text)
        await conv_store.append_turn(user_id, session_key, user_turn)

        recent = await conv_store.get_recent_turns(user_id, session_key, limit=limit)
        messages = [_build_message_from_turn(t) for t in recent]
        while messages:
            first = messages[0]
            if first.get("role") == "user" and isinstance(first.get("content"), str):
                break
            messages.pop(0)
        messages = _trim_messages_to_budget(messages)
        safe_messages = _sanitize_messages_for_claude(messages)

        system_prompt = settings.soul_md
        if memory_injector is not None:
            if local_hour is None:
                try:
                    tz = ZoneInfo(settings.scheduler_timezone)
                    local_hour = datetime.now(tz).hour
                except Exception:
                    local_hour = None
            try:
                system_prompt = await memory_injector.build_system_prompt(
                    user_id, text, settings.soul_md, local_hour=local_hour
                )
                system_prompt = sanitize_memory_injection(system_prompt)
            except Exception as e:
                logger.error("Memory injection failed, using base prompt: %s", e)

        current_display: list[str] = []
        tool_turns: list[tuple[list[dict], list[dict]]] = []
        in_tool_turn = False

        from ..ai.claude_client import TextChunk, ToolStatusChunk, ToolTurnComplete

        async def handle_event(ev: "StreamEvent") -> None:
            nonlocal in_tool_turn
            await on_event(ev)
            if isinstance(ev, TextChunk):
                if not in_tool_turn and ev.text:
                    current_display.append(ev.text)
            elif isinstance(ev, ToolStatusChunk):
                in_tool_turn = True
            elif isinstance(ev, ToolTurnComplete):
                in_tool_turn = False
                tool_turns.append((ev.assistant_blocks, ev.tool_result_blocks))

        session_manager.clear_cancel(user_id)
        try:
            async for event in claude_client.stream_with_tools(
                messages=safe_messages,
                tool_registry=tool_registry,
                user_id=user_id,
                system=system_prompt,
            ):
                if session_manager.is_cancelled(user_id):
                    break
                await handle_event(event)
                await asyncio.sleep(0)
        except Exception as exc:
            logger.exception("MessageProcessingService stream error: %s", exc)
            raise

        from ..constants import TOOL_TURN_PREFIX

        for assistant_blocks, result_blocks in tool_turns:
            asst_serialised = TOOL_TURN_PREFIX + json.dumps(assistant_blocks)
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(
                    role="assistant",
                    content=asst_serialised,
                    model_used=f"anthropic:{settings.model_complex}",
                ),
            )
            usr_serialised = TOOL_TURN_PREFIX + json.dumps(result_blocks)
            await conv_store.append_turn(
                user_id, session_key, ConversationTurn(role="user", content=usr_serialised)
            )

        final_text = "".join(current_display).strip()
        if final_text:
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(
                    role="assistant",
                    content=final_text,
                    model_used=f"anthropic:{settings.model_complex}",
                ),
            )
