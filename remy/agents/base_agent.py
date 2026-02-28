"""
Abstract base class for all Board-of-Directors sub-agents.

Each sub-agent receives the board topic, the shared analysis thread so far,
and optional user context (active goals, recent facts). It returns a plain-
text analysis string that is appended to the thread before the next agent runs.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class SubAgent(ABC):
    """
    Base class for all Board sub-agents.

    Subclasses must define:
        - name:             Short display name (e.g. "Strategy")
        - role_description: Single sentence explaining the agent's focus
        - system_prompt:    Full system prompt injected as `system` in Claude call

    And implement:
        - analyze(topic, thread, user_context) → str
    """

    #: Short display name shown in the board report header (e.g. "Strategy")
    name: str = "Agent"

    #: One-sentence description of this agent's focus area
    role_description: str = "Generic analysis agent."

    #: Full system prompt for Claude — defines the agent's persona and task
    system_prompt: str = "You are a helpful analysis agent."

    def __init__(self, claude_client: "ClaudeClient", db=None) -> None:
        self._client = claude_client
        self._db = db

    @abstractmethod
    async def analyze(
        self,
        topic: str,
        thread: list[dict],
        user_context: str = "",
    ) -> str:
        """
        Perform analysis and return a plain-text response.

        Args:
            topic:        The board topic / question posed by the user.
            thread:       Running list of previous agent analyses as message dicts
                          {"role": "assistant", "content": "<AgentName>: <analysis>"}.
                          Used to build awareness of prior analyses.
            user_context: Optional XML-formatted user memory (goals, facts) to
                          inject into the prompt so agents can personalise advice.

        Returns:
            Plain-text analysis string (Markdown OK, no Telegram escaping needed yet).
        """

    async def _call_claude(
        self,
        user_content: str,
        *,
        max_tokens: int = 600,
        model: str | None = None,
    ) -> str:
        """
        Helper: non-streaming Claude call.  Falls back to empty string on error.
        """
        import time
        import asyncio
        from ..config import settings
        from ..models import TokenUsage
        from ..analytics.call_log import log_api_call

        model = model or settings.model_complex
        t0 = time.monotonic()
        usage = TokenUsage()
        try:
            result = await self._client.complete(
                messages=[{"role": "user", "content": user_content}],
                system=self.system_prompt,
                model=model,
                max_tokens=max_tokens,
                usage_out=usage,
            )
            
            user_id = getattr(self, "_current_user_id", None)
            session_key = getattr(self, "_current_session_key", None)
            if self._db is not None and user_id is not None and session_key is not None:
                latency = int((time.monotonic() - t0) * 1000)
                asyncio.create_task(
                    log_api_call(
                        self._db,
                        user_id=user_id,
                        session_key=session_key,
                        provider="anthropic",
                        model=model,
                        category="reasoning",
                        call_site="background",
                        usage=usage,
                        latency_ms=latency,
                        fallback=False,
                    )
                )

            return result
        except Exception as exc:
            logger.error("[%s] Claude call failed: %s", self.name, exc)
            return f"[{self.name} analysis unavailable: {exc}]"

    def _build_context_block(self, thread: list[dict], user_context: str) -> str:
        """Format prior analyses + user context into a readable block."""
        parts: list[str] = []
        if user_context:
            parts.append(f"<user_context>\n{user_context}\n</user_context>")
        if thread:
            prior = "\n\n".join(m["content"] for m in thread)
            parts.append(f"<prior_analyses>\n{prior}\n</prior_analyses>")
        return "\n\n".join(parts)
