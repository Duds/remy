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

logger = logging.getLogger(__name__)

# Maximum retry attempts on transient errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds
# Rate-limit retries use longer delays since the window resets every 60s
_RATE_LIMIT_RETRY_DELAYS = [30.0, 60.0]  # seconds between attempts 1→2 and 2→3
# Maximum tool-call iterations before breaking the agentic loop
# Increased from 8 to 12 to support complex multi-step workflows (Bug 38)
_MAX_TOOL_ITERATIONS = 12

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


# The StreamEvent union type
StreamEvent = Union[TextChunk, ToolStatusChunk, ToolResultChunk, ToolTurnComplete]


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
                    system=system_with_cache,
                    messages=messages,
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
        """
        model = model or settings.model_complex
        system_prompt = system if system is not None else settings.soul_md
        tools = tool_registry.schemas

        # Enable prompt caching for static content (system prompt + tool schemas)
        system_with_cache = self._wrap_system_with_cache(system_prompt)
        tools_with_cache = self._wrap_tools_with_cache(tools)

        # Working copy of messages — we'll append assistant + tool_result turns
        working_messages = list(messages)
        accumulated_usage = TokenUsage()

        for iteration in range(_MAX_TOOL_ITERATIONS):
            logger.debug(
                "stream_with_tools iteration %d/%d, messages=%d",
                iteration + 1,
                _MAX_TOOL_ITERATIONS,
                len(working_messages),
            )

            # Collect text and tool_use blocks from this iteration
            text_buffer: list[str] = []
            tool_use_blocks: list[dict] = []  # raw dicts for history reconstruction
            assistant_content_blocks: list[dict] = []
            stop_reason: str | None = None

            # Retry loop: 429s are raised when initiating the stream (before any
            # events are yielded), so we can safely retry the whole API call.
            # Per-minute TPM limits need ~30-60s to reset, not the 2-8s used
            # for server errors.
            for attempt in range(_MAX_RETRIES):
                text_buffer = []
                tool_use_blocks = []
                assistant_content_blocks = []
                try:
                    async with self._client.messages.stream(
                        model=model,
                        max_tokens=settings.anthropic_max_tokens,
                        system=system_with_cache,
                        messages=working_messages,
                        tools=tools_with_cache,
                    ) as stream:
                        # Iterate raw events so we don't exhaust the generator before
                        # calling stream.get_final_message() below
                        async for event in stream:
                            event_type = type(event).__name__

                            # Text delta
                            if event_type == "RawContentBlockDeltaEvent":
                                delta = getattr(event, "delta", None)
                                if (
                                    delta
                                    and getattr(delta, "type", None) == "text_delta"
                                ):
                                    chunk = delta.text
                                    text_buffer.append(chunk)
                                    yield TextChunk(text=chunk)

                            # Tool use block starting
                            elif event_type == "RawContentBlockStartEvent":
                                block = getattr(event, "content_block", None)
                                if block and getattr(block, "type", None) == "tool_use":
                                    yield ToolStatusChunk(
                                        tool_name=block.name,
                                        tool_use_id=block.id,
                                        tool_input={},
                                    )

                        # After streaming, get the final message snapshot for tool_use blocks
                        final_msg = await stream.get_final_message()
                        stop_reason = final_msg.stop_reason
                        accumulated_usage = accumulated_usage + TokenUsage(
                            input_tokens=final_msg.usage.input_tokens,
                            output_tokens=final_msg.usage.output_tokens,
                            cache_creation_tokens=getattr(
                                final_msg.usage, "cache_creation_input_tokens", 0
                            )
                            or 0,
                            cache_read_tokens=getattr(
                                final_msg.usage, "cache_read_input_tokens", 0
                            )
                            or 0,
                        )

                        # Extract all content blocks for history
                        for block in final_msg.content:
                            if block.type == "text":
                                assistant_content_blocks.append(
                                    {
                                        "type": "text",
                                        "text": block.text,
                                    }
                                )
                            elif block.type == "tool_use":
                                tool_use_blocks.append(
                                    {
                                        "type": "tool_use",
                                        "id": block.id,
                                        "name": block.name,
                                        "input": block.input,
                                    }
                                )
                                assistant_content_blocks.append(
                                    {
                                        "type": "tool_use",
                                        "id": block.id,
                                        "name": block.name,
                                        "input": block.input,
                                    }
                                )
                    break  # stream completed successfully — exit retry loop

                except anthropic.RateLimitError:
                    delay = (
                        _RATE_LIMIT_RETRY_DELAYS[attempt]
                        if attempt < len(_RATE_LIMIT_RETRY_DELAYS)
                        else 60.0
                    )
                    logger.warning(
                        "Rate limited in stream_with_tools (attempt %d/%d). "
                        "Retrying in %.0fs",
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
                            "Anthropic overload %d in stream_with_tools (attempt %d/%d). "
                            "Retrying in %.1fs",
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

            # If no tool calls, we're done
            if stop_reason != "tool_use" or not tool_use_blocks:
                if usage_out is not None:
                    usage_out.input_tokens = accumulated_usage.input_tokens
                    usage_out.output_tokens = accumulated_usage.output_tokens
                    usage_out.cache_creation_tokens = (
                        accumulated_usage.cache_creation_tokens
                    )
                    usage_out.cache_read_tokens = accumulated_usage.cache_read_tokens
                return

            # Execute all tool calls and collect results
            tool_result_blocks: list[dict] = []
            for tool_block in tool_use_blocks:
                tool_name = tool_block["name"]
                tool_use_id = tool_block["id"]
                tool_input = tool_block.get("input", {})

                logger.info(
                    "Executing tool %s (id=%s) for user %d",
                    tool_name,
                    tool_use_id,
                    user_id,
                )

                try:
                    result = await tool_registry.dispatch(
                        tool_name, tool_input, user_id, chat_id, message_id
                    )
                except Exception as exc:
                    logger.error(
                        "Tool dispatch failed for %s (id=%s): %s",
                        tool_name,
                        tool_use_id,
                        exc,
                        exc_info=True,
                    )
                    result = f"Tool '{tool_name}' encountered an error: {exc}"

                yield ToolResultChunk(
                    tool_name=tool_name,
                    tool_use_id=tool_use_id,
                    result=result,
                )

                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result,
                    }
                )

            # Emit ToolTurnComplete with raw blocks for conversation history
            yield ToolTurnComplete(
                assistant_blocks=assistant_content_blocks,
                tool_result_blocks=tool_result_blocks,
            )

            # Append assistant turn + tool results to working messages, then loop
            working_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content_blocks,
                }
            )
            working_messages.append(
                {
                    "role": "user",
                    "content": tool_result_blocks,
                }
            )

        if usage_out is not None:
            usage_out.input_tokens = accumulated_usage.input_tokens
            usage_out.output_tokens = accumulated_usage.output_tokens
            usage_out.cache_creation_tokens = accumulated_usage.cache_creation_tokens
            usage_out.cache_read_tokens = accumulated_usage.cache_read_tokens
        logger.warning(
            "stream_with_tools hit max iterations (%d) for user %d",
            _MAX_TOOL_ITERATIONS,
            user_id,
        )
        # Yield a truncation note so the user knows the response was limited (Bug 38)
        yield TextChunk(
            text="\n\n_I reached my step limit for this turn. Ask me to continue or break this into smaller tasks._"
        )

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
                    system=system_with_cache,
                    messages=messages,
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
                return response.content[0].text
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
