"""
Proactive pipeline — runs a scheduler-triggered reminder through the full
Claude agentic loop and delivers the response to Telegram.

This module is intentionally thin: it reuses the same building blocks as
handlers.py (_build_message_from_turn, _trim_messages_to_budget, StreamingReply)
so that proactive triggers behave identically to user-initiated messages,
including tool use and conversation history persistence.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .handlers import _TOOL_TURN_PREFIX, _build_message_from_turn, _trim_messages_to_budget
from .session import SessionManager
from .streaming import StreamingReply
from ..ai.claude_client import TextChunk, ToolResultChunk, ToolStatusChunk, ToolTurnComplete
from ..config import settings
from ..models import ConversationTurn

if TYPE_CHECKING:
    from telegram import Bot
    from ..ai.claude_client import ClaudeClient
    from ..ai.tool_registry import ToolRegistry
    from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)


def _reminder_system_prompt(label: str) -> str:
    """
    Augment SOUL.md with a reminder-trigger context block so Claude knows
    it is acting proactively, not responding to a user message.
    """
    return (
        f"{settings.soul_md}\n\n"
        "---\n"
        "REMINDER TRIGGER: You have been woken up by a scheduled reminder Dale set.\n"
        f'Reminder: "{label}"\n\n'
        "You are initiating this conversation proactively — Dale did not just send a "
        "message. Reason about what this reminder means and take the most helpful action. "
        "Do NOT just echo the reminder label back.\n"
        "Good responses: check the calendar, draft a follow-up message, look up the "
        "grocery list, ask a focused clarifying question, or take direct action with a tool.\n"
        "Use tools if appropriate. Be concise and action-oriented."
    )


async def run_proactive_trigger(
    *,
    label: str,
    user_id: int,
    chat_id: int,
    bot: "Bot",
    claude_client: "ClaudeClient",
    tool_registry: "ToolRegistry",
    session_manager: SessionManager,
    conv_store: "ConversationStore",
) -> None:
    """
    Run a scheduler-triggered reminder through the full Claude pipeline.

    1. Loads today's conversation history for the user.
    2. Appends a synthetic "[Reminder] {label}" user turn.
    3. Calls claude_client.stream_with_tools() with a reminder-aware system prompt.
    4. Streams the response live to Telegram (editing a placeholder message).
    5. Persists both the trigger turn and the assistant response to ConversationStore
       so Dale can reply naturally and the thread continues with full context.
    """
    session_key = SessionManager.get_session_key(user_id)

    async with session_manager.get_lock(user_id):
        # ------------------------------------------------------------------ #
        # 1. Build message history                                             #
        # ------------------------------------------------------------------ #
        recent = await conv_store.get_recent_turns(user_id, session_key, limit=20)
        messages: list[dict] = [_build_message_from_turn(t) for t in recent]

        # Drop any orphaned tool turns at the end of history (can't end on a
        # tool_use block without a following tool_result).
        while messages and messages[-1].get("role") == "assistant" and isinstance(
            messages[-1].get("content"), list
        ):
            messages.pop()

        messages = _trim_messages_to_budget(messages)

        # ------------------------------------------------------------------ #
        # 2. Append the synthetic trigger message                              #
        # ------------------------------------------------------------------ #
        trigger_text = f"[Reminder] {label}"
        messages.append({"role": "user", "content": trigger_text})

        system_prompt = _reminder_system_prompt(label)

        # ------------------------------------------------------------------ #
        # 3. Send placeholder to Telegram                                      #
        # ------------------------------------------------------------------ #
        try:
            sent = await bot.send_message(
                chat_id=chat_id, text="⏰ _…_", parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(
                "Proactive trigger: could not send placeholder to chat %d: %s", chat_id, e
            )
            return

        # ------------------------------------------------------------------ #
        # 4. Stream through Claude with full tool support                      #
        # ------------------------------------------------------------------ #
        streamer = StreamingReply(sent, session_manager, user_id)
        tool_turns: list[tuple[list[dict], list[dict]]] = []
        in_tool_turn = False

        try:
            async for event in claude_client.stream_with_tools(
                messages=messages,
                tool_registry=tool_registry,
                user_id=user_id,
                system=system_prompt,
            ):
                if isinstance(event, TextChunk):
                    if not in_tool_turn:
                        await streamer.feed(event.text)

                elif isinstance(event, ToolStatusChunk):
                    in_tool_turn = True
                    try:
                        await sent.edit_text(
                            f"_⚙️ Using {event.tool_name}…_",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass

                elif isinstance(event, ToolResultChunk):
                    pass  # ToolTurnComplete follows with the blocks we need

                elif isinstance(event, ToolTurnComplete):
                    in_tool_turn = False
                    tool_turns.append(
                        (event.assistant_blocks, event.tool_result_blocks)
                    )
                    # Reset streamer so the final text response starts fresh
                    streamer = StreamingReply(sent, session_manager, user_id)

        except Exception as exc:
            logger.error(
                "Proactive pipeline stream error for user %d (automation label %r): %s",
                user_id, label, exc,
            )
            try:
                await sent.edit_text(f"⏰ Reminder: {label}\n\n_(Error generating response: {exc})_")
            except Exception:
                pass
            return

        await streamer.finalize()
        final_text = streamer.full_text.strip()

        # ------------------------------------------------------------------ #
        # 5. Persist conversation history                                       #
        # ------------------------------------------------------------------ #
        # Save the synthetic user trigger turn
        await conv_store.append_turn(
            user_id, session_key,
            ConversationTurn(role="user", content=trigger_text),
        )

        # Save tool turns (multi-block) with sentinel prefix
        for assistant_blocks, result_blocks in tool_turns:
            asst_serialised = _TOOL_TURN_PREFIX + json.dumps(assistant_blocks)
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="assistant", content=asst_serialised),
            )
            usr_serialised = _TOOL_TURN_PREFIX + json.dumps(result_blocks)
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="user", content=usr_serialised),
            )

        # Save the final assistant text turn
        if final_text:
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="assistant", content=final_text),
            )

        logger.info(
            "Proactive trigger complete for user %d (chat %d, label=%r, "
            "tool_turns=%d, response_len=%d)",
            user_id, chat_id, label, len(tool_turns), len(final_text),
        )
