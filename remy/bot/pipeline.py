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
    from ..ai.tools import ToolRegistry
    from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)

# Synthetic trigger prefix for proactive messages — parseable by Remy AI and ingest.
PROACTIVE_PREFIX = "[Proactive]"


def _trigger_text_for_proactive(label: str, context: dict | None) -> str:
    """
    Build the synthetic user message for proactive triggers so Remy AI can ingest it.

    Format: "[Proactive] type=<trigger_type> [label=<human label>]"
    - morning_briefing, afternoon_focus, evening_checkin, afternoon_check: type only (context carries intent).
    - reminder: type=reminder and the user's label (e.g. sobriety check) for clarity.
    """
    if context is not None:
        if context.get("evening_checkin"):
            return f"{PROACTIVE_PREFIX} type=evening_checkin"
        if context.get("afternoon_checkin"):
            return f"{PROACTIVE_PREFIX} type=afternoon_focus"
        if context.get("afternoon_check"):
            return f"{PROACTIVE_PREFIX} type=afternoon_check"
        # Morning briefing or other context-carrying triggers
        return f"{PROACTIVE_PREFIX} type=morning_briefing"
    return f"{PROACTIVE_PREFIX} type=reminder label={label!r}"


# Proactive trigger scenarios — system prompt templates
_PROACTIVE_SCENARIOS: dict[str, tuple[str, str]] = {
    "reminder": (
        "REMINDER TRIGGER",
        "You have been woken up by a scheduled reminder Dale set.\n"
        "{label_line}\n\n"
        "You are initiating this conversation proactively — Dale did not just send a "
        "message. Reason about what this reminder means and take the most helpful action. "
        "Do NOT just echo the reminder label back.\n"
        "Good responses: check the calendar, draft a follow-up message, look up the "
        "grocery list, ask a focused clarifying question, or take direct action with a tool.\n"
        "Use tools if appropriate. Be concise and action-oriented.",
    ),
    "briefing": (
        "MORNING BRIEFING",
        "You have structured context for Dale's day. "
        "Compose a short, warm, conversational message.\n\n"
        "- Use Australian date format (DD/MM/YYYY) and 24-hour time\n"
        "- Prioritise what matters most; don't list everything verbatim\n"
        "- Be concise and natural — you're Remy, not a bulletin\n"
        "- Include calendar highlights, top goals, and any urgent items\n"
        "- Optionally mention downloads cleanup or stale plans if relevant\n\n"
        "Structured context:\n"
        "```json\n{context_json}\n```",
    ),
    "evening_checkin": (
        "EVENING CHECK-IN",
        "Dale hasn't mentioned these goals recently. "
        "Compose a short, warm nudge — not a list. You're Remy checking in, not a task reminder.\n\n"
        "- Reference the goals naturally; one or two sentences is enough\n"
        "- If there's calendar context (today's events), you can tie it in (e.g. 'You had X today — still on for Y?')\n"
        "- The 'counters' array in structured context (when present) is the live value at send time. "
        "Acknowledge sobriety_streak when present (e.g. Day 7, Day 30) in a warm, brief way.\n"
        "- Invite a quick reply; don't overwhelm\n\n"
        "Structured context:\n"
        "```json\n{context_json}\n```",
    ),
    "afternoon_checkin": (
        "AFTERNOON FOCUS CHECK-IN",
        "Mid-day body-double nudge. "
        "Compose a short, warm focus message — you're Remy helping Dale stay on track.\n\n"
        "- If there's a top_goal, centre the nudge on it; ask how it's going\n"
        "- If there's remaining_calendar, mention what's still on today's schedule\n"
        "- Keep it to one or two sentences; encourage the next few focused hours\n"
        "- If no goals yet, gently invite Dale to name what matters today\n\n"
        "Structured context:\n"
        "```json\n{context_json}\n```",
    ),
    "afternoon_check": (
        "AFTERNOON CHECK-IN",
        "This is the daily afternoon check-in (typically 5pm). "
        "Your job is to meet Dale where he is — compassionate, context-aware, never preachy or generic.\n\n"
        "- Use what you know from memory and today's conversation: how his day went, what he's working on, how he seems\n"
        "- One or two short sentences; warmth and presence over advice\n"
        "- If context includes goals or calendar, you can gently tie in (e.g. 'You had X today — how are you doing heading into the evening?')\n"
        "- Sound like Remy checking in, not a generic reminder\n\n"
        "Structured context (goals, calendar, etc.):\n"
        "```json\n{context_json}\n```",
    ),
}


def build_proactive_system_prompt(
    scenario: str, context: dict | None = None, label: str = ""
) -> str:
    """
    Build the system prompt for a proactive trigger.

    scenario: one of "reminder", "briefing", "evening_checkin", "afternoon_checkin", "afternoon_check"
    context: structured dict for context-carrying triggers (briefing, check-ins); None for reminder
    label: user's reminder label (only used when scenario is "reminder")
    """
    if scenario not in _PROACTIVE_SCENARIOS:
        scenario = "briefing"

    title, body_template = _PROACTIVE_SCENARIOS[scenario]

    if scenario == "reminder":
        label_line = f'Reminder: "{label}"' if label else "Reminder (no label)"
        body = body_template.format(label_line=label_line)
    else:
        ctx_json = json.dumps(context or {}, indent=0)
        body = body_template.format(context_json=ctx_json)

    return f"{settings.soul_md}\n\n---\n{title}: {body}"


async def compose_proactive_message(
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
    Shared helper for context-aware proactive messages (US-remy-mediated-reminders).

    Composes and sends a proactive message via the full Claude pipeline. Used by
    morning briefing and by mediated reminders. Delegates to run_proactive_trigger.
    """
    await run_proactive_trigger(
        label=label,
        user_id=user_id,
        chat_id=chat_id,
        bot=bot,
        claude_client=claude_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        conv_store=conv_store,
        db=db,
        automation_id=automation_id,
        one_time=one_time,
        context=context,
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
    2. Appends a synthetic proactive trigger turn (parseable: [Proactive] type=...).
    3. Calls claude_client.stream_with_tools() with a reminder-aware system prompt.
    4. Streams the response live to Telegram (editing a placeholder message).
    5. Persists both the trigger turn and the assistant response to ConversationStore
       so Dale can reply naturally and the thread continues with full context.
    """
    session_key = SessionManager.get_session_key(user_id)

    async with session_manager.get_lock(user_id):
        # Determine scenario from context first (needed to decide whether to load history)
        if context is not None:
            if context.get("evening_checkin"):
                scenario = "evening_checkin"
            elif context.get("afternoon_checkin"):
                scenario = "afternoon_checkin"
            elif context.get("afternoon_check"):
                scenario = "afternoon_check"
            else:
                scenario = "briefing"
        else:
            scenario = "reminder"

        # ------------------------------------------------------------------ #
        # 1. Build message history                                             #
        # ------------------------------------------------------------------ #
        # Morning briefing: use empty history so the message is based only on
        # structured context. Avoids stale emotional/sobriety phrasing from
        # prior conversation leaking in (Bug 45).
        if scenario == "briefing":
            recent = []
        else:
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
        # 2. Append the synthetic trigger message (parseable for Remy AI)     #
        # ------------------------------------------------------------------ #
        trigger_text = _trigger_text_for_proactive(label, context)
        messages.append({"role": "user", "content": trigger_text})

        if scenario == "reminder":
            system_prompt = build_proactive_system_prompt("reminder", label=label)
        else:
            system_prompt = build_proactive_system_prompt(scenario, context)

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
        # 4b. Attach keyboard — unified factory (Phase 3.12)                   #
        #     Reminders: [Snooze 5m] [Snooze 15m] [Done]                       #
        #     Briefings: [Add to calendar] for suggested_events only           #
        # ------------------------------------------------------------------ #
        buttons_config = None
        if context is None:
            buttons_config = {
                "type": "reminder",
                "user_id": user_id,
                "chat_id": chat_id,
                "label": label,
                "automation_id": automation_id,
                "one_time": one_time,
            }
        elif context and (suggested := context.get("suggested_events")):
            actions = []
            for item in (suggested or [])[:4]:
                when = item.get("when")
                title = (item.get("title") or "Event").strip()
                if when and title:
                    btn_label = f"📅 {title}"[:32]
                    actions.append(
                        {
                            "label": btn_label,
                            "callback_id": "add_to_calendar",
                            "payload": {"title": title, "when": when},
                        }
                    )
            if actions:
                buttons_config = {
                    "type": "suggested_actions",
                    "actions": actions,
                    "user_id": user_id,
                }

        if buttons_config:
            try:
                from .handlers.callbacks import make_proactive_keyboard

                keyboard = make_proactive_keyboard(buttons_config)
                if keyboard is not None:
                    await bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=sent.message_id,
                        reply_markup=keyboard,
                    )
            except Exception as e:
                logger.debug("Could not attach proactive keyboard: %s", e)

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
