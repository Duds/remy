"""Auto-compaction service for conversation sessions.

Monitors session size and automatically triggers compaction when token
thresholds are exceeded. Integrates with the lifecycle hooks system.

Inspired by OpenClaw's session compaction with before/after hooks.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import settings
from ..hooks import HookEvents, hook_manager
from ..utils.tokens import estimate_tokens

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient
    from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)


@dataclass
class CompactionConfig:
    """Configuration for auto-compaction."""

    enabled: bool = True
    token_threshold: int = 50_000
    keep_recent_messages: int = 20
    summary_model: str = "claude-haiku-4-5-20251001"


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    compacted: bool
    original_turns: int
    original_tokens: int
    summary_tokens: int
    reason: str


class CompactionService:
    """Service for automatic session compaction.

    Monitors session size after each assistant turn and triggers compaction
    when the token count exceeds the configured threshold.

    Usage:
        service = CompactionService(conv_store, claude_client)

        # After each assistant turn:
        result = await service.check_and_compact(user_id, session_key)
        if result.compacted:
            logger.info("Session compacted: %s", result.reason)
    """

    def __init__(
        self,
        conv_store: "ConversationStore",
        claude_client: "ClaudeClient | None" = None,
        config: CompactionConfig | None = None,
    ) -> None:
        self.conv_store = conv_store
        self.claude_client = claude_client
        self.config = config or CompactionConfig()

    async def check_and_compact(
        self,
        user_id: int,
        session_key: str,
    ) -> CompactionResult:
        """Check if compaction is needed and perform it if so.

        Args:
            user_id: The user ID.
            session_key: The session key to check.

        Returns:
            CompactionResult with details of what happened.
        """
        if not self.config.enabled:
            return CompactionResult(
                compacted=False,
                original_turns=0,
                original_tokens=0,
                summary_tokens=0,
                reason="Auto-compaction disabled",
            )

        # Get all turns to estimate token count
        turns = await self.conv_store.get_recent_turns(
            user_id, session_key, limit=500
        )

        if not turns:
            return CompactionResult(
                compacted=False,
                original_turns=0,
                original_tokens=0,
                summary_tokens=0,
                reason="No turns in session",
            )

        # Skip if already compacted
        if turns and turns[0].content.startswith("[COMPACTED SUMMARY]"):
            return CompactionResult(
                compacted=False,
                original_turns=len(turns),
                original_tokens=0,
                summary_tokens=0,
                reason="Session already compacted",
            )

        # Estimate total tokens
        total_tokens = sum(estimate_tokens(t.content) for t in turns)

        if total_tokens < self.config.token_threshold:
            return CompactionResult(
                compacted=False,
                original_turns=len(turns),
                original_tokens=total_tokens,
                summary_tokens=0,
                reason=f"Below threshold ({total_tokens} < {self.config.token_threshold})",
            )

        # Emit BEFORE_COMPACTION hook
        hook_context = await hook_manager.emit(
            HookEvents.BEFORE_COMPACTION,
            {
                "user_id": user_id,
                "session_key": session_key,
                "turn_count": len(turns),
                "token_count": total_tokens,
            },
        )

        if hook_context.cancelled:
            return CompactionResult(
                compacted=False,
                original_turns=len(turns),
                original_tokens=total_tokens,
                summary_tokens=0,
                reason="Compaction cancelled by hook",
            )

        # Perform compaction
        summary = await self._generate_summary(turns)
        summary_tokens = estimate_tokens(summary)

        await self.conv_store.compact(user_id, session_key, summary)

        # Emit AFTER_COMPACTION hook
        await hook_manager.emit(
            HookEvents.AFTER_COMPACTION,
            {
                "user_id": user_id,
                "session_key": session_key,
                "original_turns": len(turns),
                "original_tokens": total_tokens,
                "summary_tokens": summary_tokens,
            },
        )

        logger.info(
            "Auto-compacted session %s: %d turns (%d tokens) → summary (%d tokens)",
            session_key,
            len(turns),
            total_tokens,
            summary_tokens,
        )

        return CompactionResult(
            compacted=True,
            original_turns=len(turns),
            original_tokens=total_tokens,
            summary_tokens=summary_tokens,
            reason=f"Exceeded threshold ({total_tokens} >= {self.config.token_threshold})",
        )

    async def _generate_summary(self, turns: list) -> str:
        """Generate a summary of the conversation turns.

        Uses Claude to create a concise summary if available,
        otherwise falls back to a simple concatenation of key points.
        """
        if self.claude_client is None:
            return self._fallback_summary(turns)

        # Build conversation text for summarisation
        conversation_text = "\n".join(
            f"{t.role.upper()}: {t.content[:500]}"
            for t in turns[-50:]  # Last 50 turns max for summary
        )

        prompt = f"""Summarise this conversation in 3-5 bullet points, capturing:
- Key topics discussed
- Important decisions or conclusions
- Any action items or follow-ups mentioned

Conversation:
{conversation_text}

Summary (bullet points only):"""

        try:
            response = await self.claude_client.complete(
                prompt,
                model=self.config.summary_model,
                max_tokens=500,
            )
            return response.strip()
        except Exception as e:
            logger.warning("Claude summarisation failed, using fallback: %s", e)
            return self._fallback_summary(turns)

    def _fallback_summary(self, turns: list) -> str:
        """Simple fallback summary when Claude is unavailable."""
        user_messages = [t for t in turns if t.role == "user"]
        if not user_messages:
            return "No user messages in session."

        # Extract first few words of each user message
        topics = []
        for t in user_messages[-10:]:
            words = t.content.split()[:10]
            topics.append(" ".join(words) + ("..." if len(t.content.split()) > 10 else ""))

        return "Topics discussed:\n" + "\n".join(f"- {topic}" for topic in topics)

    async def get_session_stats(
        self,
        user_id: int,
        session_key: str,
    ) -> dict:
        """Get statistics about a session for diagnostics."""
        turns = await self.conv_store.get_recent_turns(
            user_id, session_key, limit=500
        )

        if not turns:
            return {
                "turn_count": 0,
                "token_estimate": 0,
                "is_compacted": False,
                "needs_compaction": False,
            }

        total_tokens = sum(estimate_tokens(t.content) for t in turns)
        is_compacted = turns[0].content.startswith("[COMPACTED SUMMARY]") if turns else False

        return {
            "turn_count": len(turns),
            "token_estimate": total_tokens,
            "is_compacted": is_compacted,
            "needs_compaction": (
                not is_compacted
                and total_tokens >= self.config.token_threshold
            ),
            "threshold": self.config.token_threshold,
        }


# Module-level singleton
_compaction_service: CompactionService | None = None


def get_compaction_service(
    conv_store: "ConversationStore | None" = None,
    claude_client: "ClaudeClient | None" = None,
) -> CompactionService | None:
    """Get or create the compaction service singleton."""
    global _compaction_service
    if _compaction_service is None and conv_store is not None:
        _compaction_service = CompactionService(conv_store, claude_client)
    return _compaction_service
