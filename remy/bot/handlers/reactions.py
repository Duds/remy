"""
Telegram emoji reaction handler.

Handles MessageReactionUpdated events — fired when Dale reacts to a Remy message
with an emoji (👍, ❤️, 🔥, etc.). Maps the emoji to a human-readable context string,
builds a synthetic user turn, and asks Claude for a brief natural reply.

Reactions on messages Remy did not send, or from unauthorised users, are silently ignored.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import is_allowed
from ...models import ConversationTurn
from ..session import SessionManager
from ...config import settings

if TYPE_CHECKING:
    from ...ai.claude_client import ClaudeClient
    from ...memory.conversations import ConversationStore
    from ...memory.injector import MemoryInjector

logger = logging.getLogger(__name__)

# Maps emoji → context phrase passed to Claude in the synthetic user turn.
_REACTION_MAP: dict[str, str] = {
    "👍": "approval / understood",
    "❤️": "warm, positive",
    "🔥": "excited, this is great",
    "👎": "disagreement or disappointment",
    "🤔": "uncertain, wants more info",
    "😂": "found it funny",
    "😢": "feels bad about this",
    "🎉": "celebrating",
    "🎊": "celebrating",
    "💯": "absolutely yes, full agreement",
    "🙏": "grateful",
    "👀": "curious, paying attention",
    "✅": "done / confirmed",
    "❌": "no / rejected",
    "😍": "loves this",
    "🤩": "amazed, delighted",
    "😮": "surprised",
    "🤯": "mind blown",
    "💪": "strong, motivated",
    "🫡": "respect, acknowledged",
}

# Emojis that generally don't require a textual reply — treat as no-op
_NO_OP_EMOJI = {"✅", "👍", "👀", "🙏"}


def _sanitize_messages_for_claude(msgs: list[dict]) -> list[dict]:
    """Strip tool turns from message history before sending to Claude.

    Reaction handler calls use a simple `complete()` path that doesn't support tool
    blocks. If history contains tool turns, the API rejects them with
    'unexpected tool_use_id'. This function drops entire messages that contain any
    tool_use or tool_result block (Bug 29: partial stripping left orphaned pairs).

    After dropping tool messages, consecutive same-role messages are merged to
    preserve the alternating user/assistant structure the API requires.
    """
    # Pass 1 — drop any message that contains a tool_use or tool_result block.
    # Dropping the *whole* message (not just the block) prevents orphaned pairs.
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


def _emoji_from_reaction(reaction) -> str | None:
    """Extract the emoji string from a ReactionType object, or return None."""
    try:
        from telegram import ReactionTypeEmoji
        if isinstance(reaction, ReactionTypeEmoji):
            return reaction.emoji
    except ImportError:
        pass
    # Fallback: duck-type access
    return getattr(reaction, "emoji", None)


def make_reaction_handler(
    *,
    claude_client: "ClaudeClient | None" = None,
    conv_store: "ConversationStore | None" = None,
    memory_injector: "MemoryInjector | None" = None,
    session_manager: "SessionManager | None" = None,
):
    """
    Factory that returns the handle_reaction coroutine.
    """

    async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        reaction_update = update.message_reaction
        if reaction_update is None:
            return

        # Authorisation check
        user = reaction_update.user
        if user is None:
            return
        if not is_allowed(user.id):
            logger.debug("Reaction from unauthorised user %d — ignored", user.id)
            return

        # Only act on reactions to Remy's own messages
        if reaction_update.actor_chat is not None:
            # Channel reaction — skip
            return

        # If new_reaction is empty the user removed their reaction — skip
        new_reactions = reaction_update.new_reaction
        if not new_reactions:
            logger.debug("Reaction removed by user %d — ignored", user.id)
            return

        # Extract the first emoji (ignore multi-reaction edge cases)
        emoji = _emoji_from_reaction(new_reactions[0])
        if emoji is None:
            logger.debug("Could not extract emoji from reaction — ignored")
            return

        context_phrase = _REACTION_MAP.get(emoji, f"reacted with {emoji}")
        synthetic_text = f"[reaction: {emoji} — {context_phrase}]"

        logger.debug(
            "Reaction from user %d on message %d: %s",
            user.id,
            reaction_update.message_id,
            emoji,
        )

        if claude_client is None or conv_store is None:
            logger.debug("Reaction handler: claude_client or conv_store not available")
            return

        user_id = user.id
        thread_id: int | None = None
        session_key = SessionManager.get_session_key(user_id, thread_id)

        # Early-exit for obvious no-op reactions — skip DB read and Claude call entirely (Bug 14)
        if emoji in _NO_OP_EMOJI:
            logger.debug("Reaction %s from user %d considered no-op, skipping Claude call", emoji, user.id)
            try:
                await conv_store.append_turn(
                    user_id, session_key,
                    ConversationTurn(role="user", content=synthetic_text),
                )
            except Exception as exc:
                logger.warning("Reaction handler: failed to persist no-op turn: %s", exc)
            return

        # Load recent conversation history for context
        try:
            from .base import _build_message_from_turn, _trim_messages_to_budget
            recent = await conv_store.get_recent_turns(user_id, session_key, limit=10)
            messages = [_build_message_from_turn(t) for t in recent]
            while messages:
                if messages[0]["role"] == "user":
                    break
                messages.pop(0)
            messages = _trim_messages_to_budget(messages)
        except Exception as exc:
            logger.warning("Reaction handler: failed to load history: %s", exc)
            messages = []

        messages.append({"role": "user", "content": synthetic_text})

        # Build system prompt
        system_prompt = settings.soul_md
        if memory_injector is not None:
            try:
                system_prompt = await memory_injector.build_system_prompt(
                    user_id, synthetic_text, settings.soul_md
                )
            except Exception as exc:
                logger.warning("Reaction handler: memory injection failed: %s", exc)

        # Get a short reply from Claude — no streaming needed for a reaction response
        safe_messages = _sanitize_messages_for_claude(messages)

        try:
            reply = await claude_client.complete(
                messages=safe_messages,
                system=system_prompt,
                max_tokens=120,
            )
        except Exception as exc:
            # If Claude complains about unexpected tool_use_id, retry with minimal context
            err_text = str(exc).lower()
            logger.error("Reaction handler: Claude call failed: %s", exc)
            if "unexpected tool_use_id" in err_text or "tool_use_id" in err_text:
                try:
                    logger.debug("Reaction handler: retrying Claude call with minimal context")
                    reply = await claude_client.complete(
                        messages=[{"role": "user", "content": synthetic_text}],
                        system=system_prompt,
                        max_tokens=120,
                    )
                except Exception as exc2:
                    logger.error("Reaction handler: retry failed: %s", exc2)
                    return
            else:
                return

        if not reply or not reply.strip():
            return

        # Send reply
        try:
            await context.bot.send_message(
                chat_id=reaction_update.chat.id,
                text=reply.strip(),
            )
        except Exception as exc:
            logger.error("Reaction handler: failed to send reply: %s", exc)
            return

        # Persist both turns to conversation history
        try:
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="user", content=synthetic_text),
            )
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(
                    role="assistant",
                    content=reply.strip(),
                    model_used=f"anthropic:{settings.model_simple}",
                ),
            )
        except Exception as exc:
            logger.warning("Reaction handler: failed to persist turns: %s", exc)

    return {"reaction": handle_reaction}