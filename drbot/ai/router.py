"""
Model router with fallback chain: Claude → Ollama.
Routes simple messages to Haiku, complex messages to Sonnet.
Falls back to Ollama on Claude API errors, notifying the user inline.
"""

import logging
from typing import AsyncIterator

import anthropic

from ..config import settings
from ..exceptions import ServiceUnavailableError
from .classifier import MessageClassifier
from .claude_client import ClaudeClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes messages to the appropriate model and client.
    Provides automatic fallback to Ollama when Claude is unavailable.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        ollama_client: OllamaClient,
    ) -> None:
        self._claude = claude_client
        self._ollama = ollama_client
        self._classifier = MessageClassifier(claude_client=claude_client)

    async def stream(
        self,
        text: str,
        messages: list[dict],
        user_id: int,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Classify the message, select a model, and stream the response.
        Falls back to Ollama if Claude is unavailable.
        `system` overrides the default SOUL.md system prompt (used for memory injection).
        """
        classification = await self._classifier.classify(text)

        model = (
            settings.model_simple if classification == "simple" else settings.model_complex
        )
        logger.info("Routing to Claude %s (user %d)", model, user_id)

        async for chunk in self._stream_with_fallback(messages, model, system=system):
            yield chunk

    async def _stream_with_fallback(
        self, messages: list[dict], model: str, system: str | None = None
    ) -> AsyncIterator[str]:
        """Try Claude; fall back to Ollama on 5xx or rate-limit errors."""
        try:
            async for chunk in self._claude.stream_message(messages, model=model, system=system):
                yield chunk
        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            logger.warning("Claude unavailable (%s). Falling back to Ollama.", e)
            if not await self._ollama.is_available():
                raise ServiceUnavailableError(
                    "Both Claude and Ollama are unavailable. Please try again later."
                )
            # Notify the user that we've fallen back to the local model
            yield "\n⚠️ _Claude unavailable — responding via local Ollama model_\n\n"
            # Build a simple prompt from the last user message
            last_user_msg = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                "",
            )
            async for chunk in self._ollama.stream_generate(last_user_msg):
                yield chunk
