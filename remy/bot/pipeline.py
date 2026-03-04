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

from .handlers import (
    _TOOL_TURN_PREFIX,
    _build_message_from_turn,
    _trim_messages_to_budget,
)
from .handlers.base import _sanitize_messages_for_claude
from .session import SessionManager
from .streaming import StreamingReply
from ..ai.claude_client import (
    TextChunk,
    ToolResultChunk,
    ToolStatusChunk,
    ToolTurnComplete,
)
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


def _briefing_system_prompt(context: dict) -> str:
    """
    US-conversational-briefing-via-remy: system prompt for morning briefing.
    Injects structured context so Claude composes a natural, prioritised message.
    """
    ctx_json = json.dumps(context, indent=0)
    return (
        f"{settings.soul_md}\n\n"
        "---\n"
        "MORNING BRIEFING: You have structured context for Dale's day. "
        "Compose a short, warm, conversational message.\n\n"
        "- Use Australian date format (DD/MM/YYYY) and 24-hour time\n"
        "- Prioritise what matters most; don't list everything verbatim\n"
        "- Be concise and natural — you're Remy, not a bulletin\n"
        "- Include calendar highlights, top goals, and any urgent items\n"
        "- Optionally mention downloads cleanup or stale plans if relevant\n"
        "- If relay_unread or relay_pending are non-zero, add one line: e.g. '📬 N unread message(s) from cowork.' and/or '📋 N pending task(s) from cowork.'\n\n"
        "Structured context:\n"
        f"```json\n{ctx_json}\n```"
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
    db=None,
    automation_id: int = 0,
    one_time: bool = False,
    context: dict | None = None,
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
        recent = await conv_store.get_recent_turns(
            user_id, session_key, limit=settings.compaction_keep_recent_messages
        )
        messages: list[dict] = [_build_message_from_turn(t) for t in recent]

        # Drop any orphaned tool turns at the end of history (can't end on a
        # tool_use block without a following tool_result).
        while (
            messages
            and messages[-1].get("role") == "assistant"
            and isinstance(messages[-1].get("content"), list)
        ):
            messages.pop()

        messages = _trim_messages_to_budget(messages)
        messages = _sanitize_messages_for_claude(messages)

        # ------------------------------------------------------------------ #
        # 2. Append the synthetic trigger message                              #
        # ------------------------------------------------------------------ #
        trigger_text = f"[Reminder] {label}"
        messages.append({"role": "user", "content": trigger_text})

        if context is not None:
            system_prompt = _briefing_system_prompt(context)
        else:
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
                "Proactive trigger: could not send placeholder to chat %d: %s",
                chat_id,
                e,
            )
            return

        # ------------------------------------------------------------------ #
        # 4. Stream through Claude with full tool support                      #
        # ------------------------------------------------------------------ #
        streamer = StreamingReply(sent, session_manager, user_id)
        tool_turns: list[tuple[list[dict], list[dict]]] = []
        in_tool_turn = False

        import time
        from ..models import TokenUsage
        from ..analytics.call_log import log_api_call
        import asyncio

        usage = TokenUsage()
        t0 = time.monotonic()

        try:
            async for event in claude_client.stream_with_tools(
                messages=messages,
                tool_registry=tool_registry,
                user_id=user_id,
                system=system_prompt,
                usage_out=usage,
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
                    except Exception as e:
                        logger.debug("Failed to update tool status in pipeline: %s", e)

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
                user_id,
                label,
                exc,
            )
            err_str = str(exc)
            if "overloaded_error" in err_str or "overloaded" in err_str.lower():
                user_msg = (
                    f"⏰ Reminder: {label}\n\n_"
                    "Anthropic's API is busy right now. Try again in a few minutes._"
                )
            else:
                user_msg = (
                    f"⏰ Reminder: {label}\n\n_(Error generating response: {exc})_"
                )
            try:
                await sent.edit_text(user_msg)
            except Exception as edit_err:
                logger.debug("Failed to edit error message in pipeline: %s", edit_err)
            return

        await streamer.finalize()
        final_text = streamer.full_text.strip()

        # Bug 35/42: When the only tool is react_to_message and there's no text,
        # delete the status message — the emoji reaction is the complete response.
        _REACTION_ONLY_TOOLS = frozenset({"react_to_message"})
        tool_names = set()
        for assistant_blocks, _ in tool_turns:
            for block in assistant_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_names.add(block.get("name"))
        if tool_turns and not final_text and tool_names == _REACTION_ONLY_TOOLS:
            try:
                await sent.delete()
            except Exception as e:
                logger.debug("Could not delete react_to_message status message: %s", e)

        # ------------------------------------------------------------------ #
        # 4b. Attach keyboard to message                                      #
        #     Reminders: [Snooze 5m] [Snooze 15m] [Done]                       #
        #     Briefings: [Add to calendar] only for suggested_events (US-proactive-buttons-decisions-only)
        #     context["calendar"] = existing events (informational, no buttons) #
        # ------------------------------------------------------------------ #
        if context is None:
            try:
                from .handlers.callbacks import (
                    make_reminder_keyboard,
                    store_reminder_payload,
                )

                token = store_reminder_payload(
                    user_id=user_id,
                    chat_id=chat_id,
                    label=label,
                    automation_id=automation_id,
                    one_time=one_time,
                )
                keyboard = make_reminder_keyboard(token)
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=sent.message_id,
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.debug("Could not attach reminder keyboard: %s", e)
        elif context and (suggested := context.get("suggested_events")):
            # Decisions only: [Add to calendar] only for suggested events to add, not existing calendar
            try:
                from .handlers.callbacks import make_suggested_actions_keyboard

                actions = []
                for item in (suggested or [])[:4]:  # Max 4 buttons (keyboard limit)
                    when = item.get("when")
                    title = (item.get("title") or "Event").strip()
                    if when and title:
                        label = f"📅 {title}"[:32]
                        actions.append(
                            {
                                "label": label,
                                "callback_id": "add_to_calendar",
                                "payload": {"title": title, "when": when},
                            }
                        )
                if actions:
                    cal_keyboard = make_suggested_actions_keyboard(actions, user_id)
                    if cal_keyboard is not None:
                        await bot.edit_message_reply_markup(
                            chat_id=chat_id,
                            message_id=sent.message_id,
                            reply_markup=cal_keyboard,
                        )
            except Exception as e:
                logger.debug(
                    "Could not attach [Add to calendar] keyboard for suggested_events: %s",
                    e,
                )

        # ------------------------------------------------------------------ #
        # 5. Persist conversation history                                       #
        # ------------------------------------------------------------------ #
        # Save the synthetic user trigger turn
        await conv_store.append_turn(
            user_id,
            session_key,
            ConversationTurn(role="user", content=trigger_text),
        )

        # Save tool turns (multi-block) with sentinel prefix
        for assistant_blocks, result_blocks in tool_turns:
            asst_serialised = _TOOL_TURN_PREFIX + json.dumps(assistant_blocks)
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(
                    role="assistant",
                    content=asst_serialised,
                    model_used=f"anthropic:{settings.model_complex}",
                ),
            )
            usr_serialised = _TOOL_TURN_PREFIX + json.dumps(result_blocks)
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(role="user", content=usr_serialised),
            )

        # Save the final assistant text turn
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

        latency_ms = int((time.monotonic() - t0) * 1000)
        if db is not None:
            asyncio.create_task(
                log_api_call(
                    db,
                    user_id=user_id,
                    session_key=session_key,
                    provider="anthropic",
                    model=settings.model_complex,
                    category="proactive",
                    call_site="proactive",
                    usage=usage,
                    latency_ms=latency_ms,
                    fallback=False,
                )
            )

        logger.info(
            "Proactive trigger complete for user %d (chat %d, label=%r, "
            "tool_turns=%d, response_len=%d)",
            user_id,
            chat_id,
            label,
            len(tool_turns),
            len(final_text),
        )
