"""
Anthropic Claude API client with streaming support.
SOUL.md is injected as the system prompt on every call.
Includes exponential backoff on rate-limit and overload errors.

Also provides stream_with_tools() for native agentic tool use (function calling).

Prompt caching: Static content (system prompts, tool schemas) is cached using
Anthropic's ephemeral cache_control blocks for 90% cost reduction on cache hits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Union

import anthropic

from ..config import settings
from ..models import TokenUsage

from . import chunk_logger

logger = logging.getLogger(__name__)

# Maximum retry attempts on transient errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds
# Rate-limit retries use longer delays since the window resets every 60s
_RATE_LIMIT_RETRY_DELAYS = [30.0, 60.0]  # seconds between attempts 1→2 and 2→3
# Maximum tool-call iterations: from settings.anthropic_max_tool_iterations (default 6)

# Minimum system prompt length to enable caching (Anthropic requires 1024+ tokens)
_MIN_CACHE_TOKENS = 1024
_CHARS_PER_TOKEN_ESTIMATE = 4


# --------------------------------------------------------------------------- #
# StreamEvent tagged union (tool-aware streaming)                             #
# --------------------------------------------------------------------------- #


@dataclass
class TextChunk:
    """A partial text delta from Claude."""

    text: str


@dataclass
class ToolStatusChunk:
    """Emitted when Claude decides to call a tool (before execution)."""

    tool_name: str
    tool_use_id: str
    tool_input: dict = field(default_factory=dict)


@dataclass
class ToolResultChunk:
    """Emitted after a tool has been executed with its result."""

    tool_name: str
    tool_use_id: str
    result: str


@dataclass
class ToolTurnComplete:
    """
    Emitted after a full tool-use round trip is complete.
    Contains the raw blocks needed to reconstruct conversation history.
    """

    assistant_blocks: list[dict]  # The assistant message content blocks
    tool_result_blocks: list[dict]  # The user message content blocks (tool results)


@dataclass
class StepLimitReached:
    """
    Emitted after the step-limit TextChunk when max_iterations was hit.
    Consumer should attach the step-limit inline keyboard (Continue / Break down / Stop).
    """

    pass


@dataclass
class HandOffToSubAgent:
    """
    Emitted when max_iterations was hit; consumer should hand off to Board (sub-agent)
    instead of showing step-limit message. topic is the user's request for the Board.
    """

    topic: str


# The StreamEvent union type
StreamEvent = Union[
    TextChunk,
    ToolStatusChunk,
    ToolResultChunk,
    ToolTurnComplete,
    StepLimitReached,
    HandOffToSubAgent,
]


class AnthropicOverloadFallbackAvailable(Exception):
    """Raised when Anthropic returns overload after max retries and a fallback model is configured.
    Caller may retry stream_with_tools with model=fallback_model."""

    def __init__(self, fallback_model: str) -> None:
        self.fallback_model = fallback_model
        super().__init__(fallback_model)


def _is_overload_error(exc: anthropic.APIStatusError) -> bool:
    """True if the error is Anthropic overload (529 or overloaded_error)."""
    if exc.status_code == 529:
        return True
    return "overloaded" in str(exc).lower()


class ClaudeClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    def _should_cache(self, text: str) -> bool:
        """Check if text is long enough for Anthropic's caching (1024+ tokens)."""
        estimated_tokens = len(text) / _CHARS_PER_TOKEN_ESTIMATE
        return estimated_tokens >= _MIN_CACHE_TOKENS

    def _wrap_system_with_cache(self, system_prompt: str) -> list[dict] | str:
        """Wrap system prompt with cache_control if long enough for caching."""
        if self._should_cache(system_prompt):
            return [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return system_prompt

    def _wrap_tools_with_cache(self, tools: list[dict] | None) -> list[dict] | None:
        """Add cache_control to the last tool schema for efficient caching."""
        if not tools:
            return None
        # Cache control on last tool caches all preceding tools too
        tools_copy = [dict(t) for t in tools]
        tools_copy[-1]["cache_control"] = {"type": "ephemeral"}
        return tools_copy

    async def stream_message(
        self,
        messages: list[dict],
        model: str | None = None,
        system: str | None = None,
        usage_out: TokenUsage | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream a response from Claude, yielding text deltas as they arrive.
        `system` overrides SOUL.md if provided; otherwise SOUL.md is used.

        Uses prompt caching for system prompts >= 1024 tokens to reduce costs.
        """
        model = model or settings.model_complex
        system_prompt = system if system is not None else settings.soul_md
        system_with_cache = self._wrap_system_with_cache(system_prompt)

        for attempt in range(_MAX_RETRIES):
            try:
                async with self._client.messages.stream(
                    model=model,
                    max_tokens=settings.anthropic_max_tokens,
                    system=system_with_cache,  # type: ignore[arg-type]
                    messages=messages,  # type: ignore[arg-type]
                ) as stream:
                    async for text in stream.text_stream:
                        yield text
                    if usage_out is not None:
                        final_msg = await stream.get_final_message()
                        usage_out.input_tokens = final_msg.usage.input_tokens
                        usage_out.output_tokens = final_msg.usage.output_tokens
                        usage_out.cache_creation_tokens = (
                            getattr(final_msg.usage, "cache_creation_input_tokens", 0)
                            or 0
                        )
                        usage_out.cache_read_tokens = (
                            getattr(final_msg.usage, "cache_read_input_tokens", 0) or 0
                        )
                return  # success
            except anthropic.RateLimitError:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d). Retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                else:
                    raise
            except anthropic.APIStatusError as e:
                if e.status_code >= 500:
                    delay = _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Anthropic overload %d (attempt %d/%d). Retrying in %.1fs",
                        e.status_code,
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(delay)
                    else:
                        raise
                else:
                    raise

    async def stream_with_tools(
        self,
        messages: list[dict],
        tool_registry,  # ToolRegistry instance
        user_id: int,
        model: str | None = None,
        system: str | None = None,
        usage_out: TokenUsage | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        max_iterations: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Agentic tool-use loop: stream Claude's response, handle tool calls,
        feed results back, and continue until end_turn or max iterations.

        Yields StreamEvent instances:
          - TextChunk: partial text from Claude
          - ToolStatusChunk: Claude is about to call a tool
          - ToolResultChunk: tool has returned a result
          - ToolTurnComplete: full tool round-trip done (history reconstruction data)

        IMPORTANT: We iterate raw stream events (not text_stream) to avoid
        exhausting the underlying generator before calling get_final_message().
        Instead we use stream.current_message_snapshot after the loop.

        Uses prompt caching for system prompts and tool schemas to reduce costs.
        Requires Claude Agent SDK (pip install claude-agent-sdk) and use_sdk_agent=True.
        """
        if tool_registry is None:
            raise RuntimeError(
                "stream_with_tools requires a tool_registry. "
                "Agentic tool use is SDK-only (US-claude-agent-sdk-migration)."
            )
        from ..agents import sdk_subagents

        if not getattr(settings, "use_sdk_agent", True):
            raise RuntimeError(
                "stream_with_tools requires use_sdk_agent=True. "
                "Set REMY_USE_SDK_AGENT=1 or use_sdk_agent in config."
            )
        if not sdk_subagents.is_sdk_available():
            raise RuntimeError(
                "Claude Agent SDK required for stream_with_tools. "
                "Install with: pip install claude-agent-sdk"
            )
        async for ev in sdk_subagents.run_quick_assistant_streaming(
            messages=messages,
            registry=tool_registry,
            user_id=user_id,
            system_prompt=system if system is not None else settings.soul_md,
            model=model or settings.model_complex,
            usage_out=usage_out,
            chat_id=chat_id,
            message_id=message_id,
            max_iterations=max_iterations,
        ):
            yield ev

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 256,
        usage_out: TokenUsage | None = None,
    ) -> str:
        """
        Non-streaming completion — for classifiers, fact extraction, etc.
        Returns the full response text.

        Uses prompt caching for system prompts >= 1024 tokens to reduce costs.
        """
        model = model or settings.model_simple
        system_prompt = system if system is not None else settings.soul_md
        system_with_cache = self._wrap_system_with_cache(system_prompt)

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_with_cache,  # type: ignore[arg-type]
                    messages=messages,  # type: ignore[arg-type]
                )

                if not hasattr(response, "content"):
                    logger.error(
                        "Invalid response type: %s, value: %s", type(response), response
                    )
                    return ""
                if not response.content:
                    return ""
                if usage_out is not None:
                    usage_out.input_tokens = response.usage.input_tokens
                    usage_out.output_tokens = response.usage.output_tokens
                    usage_out.cache_creation_tokens = (
                        getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                    )
                    usage_out.cache_read_tokens = (
                        getattr(response.usage, "cache_read_input_tokens", 0) or 0
                    )
                first = response.content[0]
                return getattr(first, "text", "")
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                if isinstance(e, anthropic.APIStatusError) and e.status_code < 500:
                    raise
                delay = _RETRY_BASE_DELAY * (2**attempt)
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception as e:
                logger.error(
                    "Unexpected error in complete() with model=%s: %s (type: %s)",
                    model,
                    e,
                    type(e).__name__,
                    exc_info=True,
                )
                raise

        return ""

    async def ping(self) -> bool:
        """Lightweight availability check using the models list endpoint."""
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
