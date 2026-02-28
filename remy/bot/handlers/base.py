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
            blocks = json.loads(turn.content[len(_TOOL_TURN_PREFIX):])
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
            total_tokens, hard_ceiling,
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
        await update.message.reply_text(
            "You are not authorised to use this bot."
        )
        return True
    return False


def google_not_configured(service: str) -> str:
    """Return a standard message for unconfigured Google services."""
    return (
        f"❌ Google {service} not configured.\n"
        "Run `python scripts/setup_google_auth.py` to authenticate."
    )
