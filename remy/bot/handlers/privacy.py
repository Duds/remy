"""
Privacy audit handler.

Contains the privacy audit command for guided privacy/digital fingerprint auditing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from .base import reject_unauthorized
from ..session import SessionManager
from ...models import ConversationTurn

if TYPE_CHECKING:
    from ...memory.conversations import ConversationStore
    from ...ai.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def make_privacy_handlers(
    *,
    session_manager: SessionManager,
    conv_store: "ConversationStore",
    claude_client=None,
    tool_registry: "ToolRegistry | None" = None,
):
    """
    Factory that returns privacy-related handlers.
    
    Returns a dict of command_name -> handler_function.
    """

    async def privacy_audit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /privacy-audit — start a guided privacy/digital fingerprint audit.

        Initiates a multi-step conversation where Remy asks for identifiers
        (names, emails, usernames) and searches for data broker presence,
        breach exposure, and privacy hygiene issues.
        """
        if await reject_unauthorized(update):
            return

        if claude_client is None:
            await update.message.reply_text("Privacy audit unavailable — no Claude client.")
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)

        privacy_audit_system = """You are conducting a privacy audit for the user. Guide them through these steps:

1. **Gather identifiers**: Ask which names, email addresses, or usernames they want to check. Be specific — ask for their full name, any aliases, primary email, and any usernames they use on social media or forums.

2. **Search for exposure**: For each identifier provided, use the web_search tool to look up:
   - Data broker sites (e.g. "john smith whitepages", "john.smith@email.com data broker")
   - Breach databases (e.g. "john.smith@email.com breach", "email haveibeenpwned")
   - Social media presence and public profiles
   - Any other publicly visible information

3. **Assess exposure level**: For each identifier, summarise:
   - LOW: Minimal public presence, no known breaches
   - MEDIUM: Some public info or minor breaches (old, password-only)
   - HIGH: Significant exposure, recent breaches, or sensitive data visible

4. **Provide action items**: Offer a prioritised list of steps:
   - Opt-out links for data brokers found
   - Password changes for breached accounts
   - 2FA recommendations for exposed accounts
   - Privacy setting adjustments for social profiles

IMPORTANT:
- Do NOT store the user's personal identifiers as memory facts unless they explicitly ask.
- Be upfront that results are based on public web search and are not exhaustive.
- If the user seems uncomfortable, remind them they can stop at any time.

Start by introducing the audit and asking for the first identifier to check."""

        initial_message = (
            "The user has requested a privacy audit. Begin the guided audit process."
        )

        thread_id: int | None = getattr(update.message, "message_thread_id", None)
        session_key = SessionManager.get_session_key(user_id, thread_id)
        async with session_manager.get_lock(user_id):
            await conv_store.add_turn(
                session_key,
                ConversationTurn(role="user", content="/privacy-audit"),
            )

            if tool_registry is not None:
                sent = await update.message.reply_text("🔒 Starting privacy audit…")

                try:
                    response_parts = []
                    from ...ai.claude_client import TextChunk
                    async for event in claude_client.stream_with_tools(
                        messages=[{"role": "user", "content": initial_message}],
                        tool_registry=tool_registry,
                        user_id=user_id,
                        system=privacy_audit_system,
                    ):
                        if isinstance(event, TextChunk):
                            response_parts.append(event.text)

                    response = "".join(response_parts)
                except Exception as exc:
                    logger.error("Privacy audit error for user %d: %s", user_id, exc)
                    await sent.edit_text(f"❌ Could not start privacy audit: {exc}")
                    return

                await conv_store.add_turn(
                    session_key,
                    ConversationTurn(role="assistant", content=response),
                )

                if response:
                    await sent.edit_text(
                        f"🔒 *Privacy Audit*\n\n{response}",
                        parse_mode="Markdown",
                    )
                else:
                    await sent.edit_text(
                        "🔒 *Privacy Audit*\n\nReady to begin. What name, email, or username "
                        "would you like me to check first?",
                        parse_mode="Markdown",
                    )
            else:
                try:
                    response = await claude_client.complete(
                        messages=[{"role": "user", "content": initial_message}],
                        system=privacy_audit_system,
                        max_tokens=800,
                    )
                except Exception as exc:
                    logger.error("Privacy audit error for user %d: %s", user_id, exc)
                    await update.message.reply_text(f"❌ Could not start privacy audit: {exc}")
                    return

                await conv_store.add_turn(
                    session_key,
                    ConversationTurn(role="assistant", content=response),
                )

                await update.message.reply_text(
                    f"🔒 *Privacy Audit*\n\n{response}",
                    parse_mode="Markdown",
                )

    return {
        "privacy-audit": privacy_audit_command,
    }
