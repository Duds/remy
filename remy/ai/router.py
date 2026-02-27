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
from .mistral_client import MistralClient
from .moonshot_client import MoonshotClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes messages to the appropriate model based on task category and context.
    Orchestrates between Claude, Mistral, Moonshot, and Ollama.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        mistral_client: MistralClient,
        moonshot_client: MoonshotClient,
        ollama_client: OllamaClient,
    ) -> None:
        self._claude = claude_client
        self._mistral = mistral_client
        self._moonshot = moonshot_client
        self._ollama = ollama_client
        self._classifier = MessageClassifier(claude_client=claude_client)
        self._last_model = "unknown"

    @property
    def last_model(self) -> str:
        """Returns the name of the model effectively used in the last stream."""
        return self._last_model

    async def stream(
        self,
        text: str,
        messages: list[dict],
        user_id: int,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Classify, route, and stream the response.
        """
        category = await self._classifier.classify(text)
        
        # Approximate context length (characters / 4 as a rough token heuristic)
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if system:
            total_chars += len(system)
        approx_tokens = total_chars // 4

        logger.info(
            "Routing task: category=%s, approx_tokens=%d (user %d)",
            category, approx_tokens, user_id
        )

        # Mapping logic from model_orchestration_refactor.md
        if category == "routine":
            if approx_tokens < 50000:
                async for chunk in self._stream_with_fallback("mistral", messages, model=settings.mistral_model_medium):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_simple, system=system):
                    yield chunk

        elif category == "summarization":
            if approx_tokens < 100000:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_simple, system=system):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("mistral", messages, model=settings.mistral_model_large):
                    yield chunk

        elif category == "reasoning":
            if approx_tokens > 128000:
                async for chunk in self._stream_with_fallback("moonshot", messages, model=settings.moonshot_model_k2_thinking):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system):
                    yield chunk

        elif category == "coding":
            if approx_tokens < 128000:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("moonshot", messages, model=settings.moonshot_model_k2_thinking):
                    yield chunk

        elif category == "safety":
            async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system):
                yield chunk

        elif category == "persona":
            async for chunk in self._stream_with_fallback("moonshot", messages, model=settings.moonshot_model_v1):
                yield chunk

        else:
            async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system):
                yield chunk

    async def _stream_with_fallback(
        self, provider: str, messages: list[dict], model: str | None = None, system: str | None = None
    ) -> AsyncIterator[str]:
        """Try a cloud provider; fall back to Ollama on failure."""
        effective_model = model or "default"
        self._last_model = f"{provider}:{effective_model}"
        
        logger.info("Streaming via %s: model=%s", provider, effective_model)
        
        try:
            if provider == "claude":
                async for chunk in self._claude.stream_message(messages, model=model, system=system):
                    yield chunk
            elif provider == "mistral":
                async for chunk in self._mistral.stream_chat(messages, model=model):
                    yield chunk
            elif provider == "moonshot":
                async for chunk in self._moonshot.stream_chat(messages, model=model):
                    yield chunk
        except Exception as e:
            logger.warning("%s unavailable (%s). Falling back to Ollama.", provider.capitalize(), e)
            self._last_model = "ollama:local"
            if not await self._ollama.is_available():
                raise ServiceUnavailableError(
                    f"Both {provider.capitalize()} and Ollama are unavailable. Please try again later."
                )
            yield f"\n⚠️ _{provider.capitalize()} unavailable — responding via local Ollama model_\n\n"
            async for chunk in self._ollama.stream_chat(messages):
                yield chunk
