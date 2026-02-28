"""
Model router with fallback chain: Claude → Ollama.
Routes simple messages to Haiku, complex messages to Sonnet.
Falls back to Ollama on Claude API errors, notifying the user inline.
"""

import logging
from typing import AsyncIterator

import anthropic

from ..bot.session import SessionManager
from ..config import settings
from ..exceptions import ServiceUnavailableError
from ..models import TokenUsage
from .classifier import MessageClassifier
from .claude_client import ClaudeClient
from .mistral_client import MistralClient
from .moonshot_client import MoonshotClient
from .ollama_client import OllamaClient
from ..analytics.call_log import log_api_call

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
        db = None,
    ) -> None:
        self._claude = claude_client
        self._mistral = mistral_client
        self._moonshot = moonshot_client
        self._ollama = ollama_client
        self._db = db
        self._classifier = MessageClassifier(claude_client=claude_client)
        self._last_model = "unknown"
        self._last_usage = TokenUsage()

    @property
    def last_model(self) -> str:
        """Returns the name of the model effectively used in the last stream."""
        return self._last_model

    @property
    def last_usage(self) -> TokenUsage:
        """Returns the token usage from the last stream call."""
        return self._last_usage

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
        category = await self._classifier.classify(text, user_id=user_id, db=self._db)
        
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
                async for chunk in self._stream_with_fallback("mistral", messages, model=settings.mistral_model_medium, user_id=user_id, category=category):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_simple, system=system, user_id=user_id, category=category):
                    yield chunk

        elif category == "summarization":
            if approx_tokens < 100000:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_simple, system=system, user_id=user_id, category=category):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("mistral", messages, model=settings.mistral_model_large, user_id=user_id, category=category):
                    yield chunk

        elif category == "reasoning":
            if approx_tokens > 128000:
                async for chunk in self._stream_with_fallback("moonshot", messages, model=settings.moonshot_model_k2_thinking, user_id=user_id, category=category):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system, user_id=user_id, category=category):
                    yield chunk

        elif category == "coding":
            if approx_tokens < 128000:
                async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system, user_id=user_id, category=category):
                    yield chunk
            else:
                async for chunk in self._stream_with_fallback("moonshot", messages, model=settings.moonshot_model_k2_thinking, user_id=user_id, category=category):
                    yield chunk

        elif category == "safety":
            async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system, user_id=user_id, category=category):
                yield chunk

        elif category == "persona":
            async for chunk in self._stream_with_fallback("moonshot", messages, model=settings.moonshot_model_v1, user_id=user_id, category=category):
                yield chunk

        else:
            async for chunk in self._stream_with_fallback("claude", messages, model=settings.model_complex, system=system, user_id=user_id, category=category):
                yield chunk

    async def _stream_with_fallback(
        self, provider: str, messages: list[dict], model: str | None = None, system: str | None = None, user_id: int | None = None, category: str = "unknown"
    ) -> AsyncIterator[str]:
        """Try a cloud provider; fall back to Ollama on failure."""
        import time
        import asyncio
        effective_model = model or "default"
        self._last_model = f"{provider}:{effective_model}"
        self._last_usage = TokenUsage()

        logger.info("Streaming via %s: model=%s", provider, effective_model)

        t0 = time.monotonic()
        fallback_used = False
        try:
            if provider == "claude":
                async for chunk in self._claude.stream_message(messages, model=model, system=system, usage_out=self._last_usage):
                    yield chunk
            elif provider == "mistral":
                async for chunk in self._mistral.stream_chat(messages, model=model, usage_out=self._last_usage):
                    yield chunk
            elif provider == "moonshot":
                async for chunk in self._moonshot.stream_chat(messages, model=model, usage_out=self._last_usage):
                    yield chunk
        except Exception as e:
            logger.warning("%s unavailable (%s). Falling back to Ollama.", provider.capitalize(), e)
            self._last_model = "ollama:local"
            fallback_used = True
            if not await self._ollama.is_available():
                raise ServiceUnavailableError(
                    f"Both {provider.capitalize()} and Ollama are unavailable. Please try again later."
                )
            yield f"\n⚠️ _{provider.capitalize()} unavailable — responding via local Ollama model_\n\n"
            
            t0 = time.monotonic()  # Reset latency timer for the fallback attempt
            async for chunk in self._ollama.stream_chat(messages, usage_out=self._last_usage):
                yield chunk
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            if self._db and user_id is not None:
                session_key = SessionManager.get_session_key(user_id)
                actual_provider, actual_model = self._last_model.split(":", 1)
                asyncio.create_task(
                    log_api_call(
                        self._db,
                        user_id=user_id,
                        session_key=session_key,
                        provider=actual_provider,
                        model=actual_model,
                        category=category,
                        call_site="router",
                        usage=self._last_usage,
                        latency_ms=latency_ms,
                        fallback=fallback_used,
                    )
                )
