"""
Base utilities for Telegram handlers.

Contains shared utilities, authentication checks, and message building functions
used across all handler modules.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING

from telegram import Update

from ...config import settings

# Tools that trigger an automatic completion reaction (🤩) on the user's message
# when they complete successfully. Uses Telegram-valid emoji per Bug 39.
COMPLETION_REACTION_TOOLS = frozenset(
    {
        "label_emails",  # archive, trash, modify labels
        "create_calendar_event",
        "remove_reminder",  # delete automation
        "manage_memory",  # add/update/delete facts
        "manage_goal",  # add/update/complete/abandon goals
        "write_file",
        "append_file",
    }
)
COMPLETION_REACTION_EMOJI = "🤩"  # Telegram-valid; ✅ not supported
from ...constants import WORKING_MESSAGES, TOOL_TURN_PREFIX
from ...ai.input_validator import RateLimiter
from ...utils.tokens import estimate_tokens

if TYPE_CHECKING:
    from ...models import ConversationTurn

logger = logging.getLogger(__name__)

# Sentinel prefix used to serialise multi-block tool turns into JSONL conversation store
_TOOL_TURN_PREFIX = TOOL_TURN_PREFIX

# Rate limiter: max 10 messages per minute per user
_rate_limiter = RateLimiter(max_messages_per_minute=10)

# Track task start times for 2-hour timeout enforcement
_task_start_times: dict[int, float] = {}
TASK_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 hours

# Pending two-step write state: user_id -> sanitized path
_pending_writes: dict[int, str] = {}

# Pending archive confirmation: user_id -> list of Gmail message IDs
_pending_archive: dict[int, list[str]] = {}

# Per-user concurrency control: prevents resource exhaustion from rapid messages
_user_active_requests: dict[int, int] = {}
_user_request_lock = asyncio.Lock()


def _build_message_from_turn(turn: "ConversationTurn") -> dict:
    """
    Convert a ConversationTurn back into an Anthropic messages dict.
    Tool turns are stored as JSON under a sentinel prefix; regular turns
    are plain text.
    """
    if turn.content.startswith(_TOOL_TURN_PREFIX):
        try:
            blocks = json.loads(turn.content[len(_TOOL_TURN_PREFIX) :])
            return {"role": turn.role, "content": blocks}
        except (json.JSONDecodeError, ValueError):
            pass
    return {"role": turn.role, "content": turn.content}


def _get_history_token_budget() -> int:
    """Calculate history token budget from settings (70% of max input tokens)."""
    return int(settings.max_input_tokens_per_request * 0.7)


def _get_working_msg() -> str:
    """Get a random working message for display while processing."""
    return random.choice(WORKING_MESSAGES)


class MessageRotator:
    """
    Background task that rotates working messages on a Telegram message
    at random intervals until stopped.
    """

    def __init__(self, message, user_id: int):
        self._message = message
        self._user_id = user_id
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def _rotate_loop(self):
        last_msg = ""
        while not self._stop_event.is_set():
            pool = [m for m in WORKING_MESSAGES if m != last_msg]
            msg = random.choice(pool)
            last_msg = msg

            try:
                await self._message.edit_text(msg)
            except Exception as e:
                logger.debug("Message edit failed (rate limit or deleted): %s", e)

            wait_time = random.uniform(0.5, 2.5)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_time)
            except asyncio.TimeoutError:
                continue

    def start(self):
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._rotate_loop())

    async def stop(self):
        if self._task:
            self._stop_event.set()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def _sanitize_messages_for_claude(msgs: list[dict]) -> list[dict]:
    """Strip tool turns from message history before sending to Claude.

    If history contains orphaned tool_use or tool_result blocks (e.g. after
    trimming or session boundary), the API rejects with 'unexpected tool_use_id'.
    This drops entire messages that contain any tool_use or tool_result block
    (Bug 36, Bug 20, Bug 29). After dropping, consecutive same-role messages
    are merged to preserve the alternating user/assistant structure.
    """
    # Pass 1 — drop any message that contains a tool_use or tool_result block.
    filtered: list[dict] = []
    for m in msgs:
        content = m.get("content")
        if isinstance(content, list):
            has_tool = any(
                isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
                for b in content
            )
            if has_tool:
                continue
            # No tool blocks — collapse to plain text
            parts: list[str] = []
            for b in content:
                if not isinstance(b, dict):
                    parts.append(str(b))
                elif b.get("type") == "text":
                    parts.append(b.get("text") or b.get("content") or "")
                else:
                    parts.append(str(b.get("content") or b.get("text") or ""))
            joined = "\n".join(p for p in parts if p)
            if not joined:
                continue
            filtered.append({"role": m.get("role"), "content": joined})
        else:
            filtered.append(m)

    # Pass 2 — merge consecutive same-role messages (artifact of dropping tool turns).
    merged: list[dict] = []
    for m in filtered:
        if merged and merged[-1].get("role") == m.get("role"):
            prev_content = merged[-1]["content"]
            curr_content = m.get("content", "")
            merged[-1]["content"] = f"{prev_content}\n{curr_content}"
        else:
            merged.append(dict(m))
    return merged


def _trim_messages_to_budget(messages: list[dict]) -> list[dict]:
    """
    Drop the oldest message pairs from history if the token count exceeds
    the configured budget. Always preserves at least the last 4 messages so
    that the immediate prior exchange stays intact.

    Uses estimate_tokens() for fast token counting without API calls.
    Pre-calculates message sizes to avoid O(n²) re-serialisation.

    Enforces a hard ceiling from settings.max_input_tokens_per_request to
    prevent runaway costs.
    """
    if len(messages) <= 4:
        return messages

    history_budget = _get_history_token_budget()
    hard_ceiling = settings.max_input_tokens_per_request

    msg_tokens = [estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages]
    total_tokens = sum(msg_tokens)

    if total_tokens > hard_ceiling * 0.9:
        logger.warning(
            "Message history approaching hard ceiling: %d tokens (ceiling: %d)",
            total_tokens,
            hard_ceiling,
        )

    start_idx = 0
    while len(messages) - start_idx > 4 and total_tokens > history_budget:
        total_tokens -= msg_tokens[start_idx] + msg_tokens[start_idx + 1]
        start_idx += 2

    while len(messages) - start_idx > 2 and total_tokens > hard_ceiling:
        total_tokens -= msg_tokens[start_idx] + msg_tokens[start_idx + 1]
        start_idx += 2
        logger.warning("Hard ceiling exceeded, dropping additional messages")

    return messages[start_idx:]


def is_allowed(user_id: int) -> bool:
    """Check if a user is allowed to use the bot."""
    if not settings.telegram_allowed_users:
        return True
    return user_id in settings.telegram_allowed_users


async def reject_unauthorized(update: Update) -> bool:
    """Reject unauthorized users with a message. Returns True if rejected."""
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("You are not authorised to use this bot.")
        return True
    return False


async def apply_completion_reaction(
    bot,
    chat_id: int | None,
    message_id: int | None,
    tool_turns: list[tuple[list[dict], list[dict]]],
) -> None:
    """Apply 🤩 reaction to the user's message when an allowlisted tool completes successfully.

    US-emoji-reactions-feedback: pipeline-level reaction for task completion.
    Graceful fallback: log WARNING on failure, never surface to user.
    """
    if chat_id is None or message_id is None or not tool_turns:
        return

    for assistant_blocks, result_blocks in tool_turns:
        result_by_id = {
            b.get("tool_use_id"): b.get("content")
            for b in result_blocks
            if isinstance(b, dict)
        }
        for block in assistant_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name not in COMPLETION_REACTION_TOOLS:
                continue
            content = result_by_id.get(block.get("id"), "")
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            if "encountered an error" in str(content):
                continue
            try:
                from telegram import ReactionTypeEmoji

                await bot.set_message_reaction(
                    chat_id=chat_id,
                    message_id=message_id,
                    reaction=[ReactionTypeEmoji(emoji=COMPLETION_REACTION_EMOJI)],
                )
                logger.debug(
                    "Applied completion reaction %s for tool %s on message %d",
                    COMPLETION_REACTION_EMOJI,
                    name,
                    message_id,
                )
            except Exception as exc:
                logger.warning("set_message_reaction (completion) failed: %s", exc)
            return  # One reaction per message


def google_not_configured(service: str) -> str:
    """Return a standard message for unconfigured Google services."""
    return (
        f"❌ Google {service} not configured.\n"
        "Run `python scripts/setup_google_auth.py` to authenticate."
    )
