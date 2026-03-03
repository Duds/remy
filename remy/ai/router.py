"""
Model router with fallback chain: Claude Desktop → Claude API → Ollama.
Routes simple messages to Haiku, complex messages to Sonnet.
When CLAUDE_DESKTOP_ENABLED=true, Claude-bound requests prefer the CLI
(subscription) over the API; falls back on circuit-open or any failure.
Falls back to Ollama on Claude API errors, notifying the user inline.

Uses circuit breakers to prevent cascading failures when providers are down.
"""

import logging
from typing import AsyncIterator

from ..bot.session import SessionManager
from ..config import settings
from ..exceptions import ServiceUnavailableError
from ..models import TokenUsage
from ..utils.circuit_breaker import CircuitOpenError, get_circuit_breaker
from .classifier import MessageClassifier
from .claude_client import ClaudeClient
from .claude_desktop_client import ClaudeDesktopClient
from .mistral_client import MistralClient
from .moonshot_client import MoonshotClient
from .ollama_client import OllamaClient
from ..analytics.call_log import log_api_call

logger = logging.getLogger(__name__)


class ModelRouter:
    """
    Routes messages to the appropriate model based on task category and context.
    Orchestrates between Claude Desktop, Claude API, Mistral, Moonshot, and Ollama.

    Fallback chain for Claude-bound requests:
        claude_desktop → claude (API) → ollama
    Mistral/Moonshot paths:
        mistral → ollama
        moonshot → ollama
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        mistral_client: MistralClient,
        moonshot_client: MoonshotClient,
        ollama_client: OllamaClient,
        db=None,
        claude_desktop_client: ClaudeDesktopClient | None = None,
    ) -> None:
        self._claude = claude_client
        self._mistral = mistral_client
        self._moonshot = moonshot_client
        self._ollama = ollama_client
        self._db = db
        self._claude_desktop = claude_desktop_client
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
        """
        Try a cloud provider with circuit breaker protection; fall back on failure.

        For Claude-bound requests, when CLAUDE_DESKTOP_ENABLED=true the chain is:
            claude_desktop → claude (API) → ollama
        All other providers fall back directly to Ollama on failure.

        Circuit breakers prevent cascading failures by failing fast when a provider
        is experiencing issues, rather than waiting for timeouts on every request.
        Desktop and API have independent circuit breakers so a failing Desktop does
        not trip the API breaker.
        """
        import time
        import asyncio
        effective_model = model or "default"
        self._last_model = f"{provider}:{effective_model}"
        self._last_usage = TokenUsage()

        breaker = get_circuit_breaker(provider, failure_threshold=5, recovery_timeout=60.0)
        logger.info("Streaming via %s: model=%s (circuit: %s)", provider, effective_model, breaker.state.value)

        t0 = time.monotonic()
        fallback_used = False

        try:
            # ── Claude Desktop first (subscription-first routing) ────────────────
            if (
                provider == "claude"
                and settings.claude_desktop_enabled
                and self._claude_desktop is not None
            ):
                desktop_breaker = get_circuit_breaker(
                    "claude_desktop", failure_threshold=5, recovery_timeout=60.0
                )
                if desktop_breaker.is_open:
                    logger.info("Claude Desktop circuit open — routing direct to Claude API.")
                else:
                    # Run availability check (cached after first call)
                    if self._claude_desktop._available is None:
                        self._claude_desktop._available = await self._claude_desktop._check()
                    if self._claude_desktop._available:
                        try:
                            self._last_model = f"claude_desktop:{effective_model}"
                            async for chunk in self._claude_desktop.stream_message(
                                messages, system=system, usage_out=self._last_usage
                            ):
                                yield chunk
                            await desktop_breaker._record_success()
                            return  # Done — skip API call
                        except Exception as desktop_err:
                            await desktop_breaker._record_failure(desktop_err)
                            logger.warning(
                                "Claude Desktop failed (%s) — falling back to Claude API.",
                                desktop_err,
                            )
                            self._last_model = f"{provider}:{effective_model}"

            # ── Primary provider ─────────────────────────────────────────────────
            if breaker.is_open:
                raise CircuitOpenError(provider, breaker.recovery_timeout)

            if provider == "claude":
                async for chunk in self._claude.stream_message(messages, model=model, system=system, usage_out=self._last_usage):
                    yield chunk
            elif provider == "mistral":
                async for chunk in self._mistral.stream_chat(messages, model=model, usage_out=self._last_usage):
                    yield chunk
            elif provider == "moonshot":
                async for chunk in self._moonshot.stream_chat(messages, model=model, usage_out=self._last_usage):
                    yield chunk

            await breaker._record_success()

        except CircuitOpenError as e:
            logger.warning("Circuit open for %s (retry in %.0fs). Falling back to Ollama.", provider, e.retry_after)
            fallback_used = True
            async for chunk in self._fallback_to_ollama(messages, provider, t0):
                yield chunk

        except Exception as e:
            await breaker._record_failure(e)
            logger.warning("%s unavailable (%s). Falling back to Ollama.", provider.capitalize(), e)
            fallback_used = True
            async for chunk in self._fallback_to_ollama(messages, provider, t0):
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

    async def _fallback_to_ollama(
        self, messages: list[dict], original_provider: str, t0: float
    ) -> AsyncIterator[str]:
        """Fall back to Ollama when primary provider fails."""
        self._last_model = "ollama:local"
        
        if not await self._ollama.is_available():
            raise ServiceUnavailableError(
                f"Both {original_provider.capitalize()} and Ollama are unavailable. Please try again later."
            )
        
        yield f"\n⚠️ _{original_provider.capitalize()} unavailable — responding via local Ollama model_\n\n"
        
        async for chunk in self._ollama.stream_chat(messages, usage_out=self._last_usage):
            yield chunk
