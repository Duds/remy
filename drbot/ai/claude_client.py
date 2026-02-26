"""
Anthropic Claude API client with streaming support.
SOUL.md is injected as the system prompt on every call.
Includes exponential backoff on rate-limit and overload errors.

Also provides stream_with_tools() for native agentic tool use (function calling).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Union

import anthropic

from ..config import settings

logger = logging.getLogger(__name__)

# Maximum retry attempts on transient errors
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds
# Maximum tool-call iterations before breaking the agentic loop
_MAX_TOOL_ITERATIONS = 5


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
    assistant_blocks: list[dict]   # The assistant message content blocks
    tool_result_blocks: list[dict] # The user message content blocks (tool results)


# The StreamEvent union type
StreamEvent = Union[TextChunk, ToolStatusChunk, ToolResultChunk, ToolTurnComplete]


class ClaudeClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream_message(
        self,
        messages: list[dict],
        model: str | None = None,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream a response from Claude, yielding text deltas as they arrive.
        `system` overrides SOUL.md if provided; otherwise SOUL.md is used.
        """
        model = model or settings.model_complex
        system_prompt = system if system is not None else settings.soul_md

        for attempt in range(_MAX_RETRIES):
            try:
                async with self._client.messages.stream(
                    model=model,
                    max_tokens=settings.anthropic_max_tokens,
                    system=system_prompt,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield text
                return  # success
            except anthropic.RateLimitError as e:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d). Retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
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
                        e.status_code, attempt + 1, _MAX_RETRIES, delay,
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
        """
        model = model or settings.model_complex
        system_prompt = system if system is not None else settings.soul_md
        tools = tool_registry.schemas

        # Working copy of messages — we'll append assistant + tool_result turns
        working_messages = list(messages)

        for iteration in range(_MAX_TOOL_ITERATIONS):
            logger.debug(
                "stream_with_tools iteration %d/%d, messages=%d",
                iteration + 1, _MAX_TOOL_ITERATIONS, len(working_messages),
            )

            # Collect text and tool_use blocks from this iteration
            text_buffer: list[str] = []
            tool_use_blocks: list[dict] = []  # raw dicts for history reconstruction

            async with self._client.messages.stream(
                model=model,
                max_tokens=settings.anthropic_max_tokens,
                system=system_prompt,
                messages=working_messages,
                tools=tools,
            ) as stream:
                # Iterate raw events so we don't exhaust the generator before
                # calling stream.get_final_message() below
                async for event in stream:
                    event_type = type(event).__name__

                    # Text delta
                    if event_type == "RawContentBlockDeltaEvent":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
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

                # Extract all content blocks for history
                assistant_content_blocks = []
                for block in final_msg.content:
                    if block.type == "text":
                        assistant_content_blocks.append({
                            "type": "text",
                            "text": block.text,
                        })
                    elif block.type == "tool_use":
                        tool_use_blocks.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                        assistant_content_blocks.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

            # If no tool calls, we're done
            if stop_reason != "tool_use" or not tool_use_blocks:
                return

            # Execute all tool calls and collect results
            tool_result_blocks: list[dict] = []
            for tool_block in tool_use_blocks:
                tool_name = tool_block["name"]
                tool_use_id = tool_block["id"]
                tool_input = tool_block.get("input", {})

                logger.info(
                    "Executing tool %s (id=%s) for user %d",
                    tool_name, tool_use_id, user_id,
                )

                result = await tool_registry.dispatch(tool_name, tool_input, user_id)

                yield ToolResultChunk(
                    tool_name=tool_name,
                    tool_use_id=tool_use_id,
                    result=result,
                )

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                })

            # Emit ToolTurnComplete with raw blocks for conversation history
            yield ToolTurnComplete(
                assistant_blocks=assistant_content_blocks,
                tool_result_blocks=tool_result_blocks,
            )

            # Append assistant turn + tool results to working messages, then loop
            working_messages.append({
                "role": "assistant",
                "content": assistant_content_blocks,
            })
            working_messages.append({
                "role": "user",
                "content": tool_result_blocks,
            })

        logger.warning(
            "stream_with_tools hit max iterations (%d) for user %d",
            _MAX_TOOL_ITERATIONS, user_id,
        )

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        system: str | None = None,
        max_tokens: int = 256,
    ) -> str:
        """
        Non-streaming completion — for classifiers, fact extraction, etc.
        Returns the full response text.
        """
        model = model or settings.model_simple
        system_prompt = system if system is not None else settings.soul_md

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=messages,
                )

                if not hasattr(response, 'content'):
                    logger.error("Invalid response type: %s, value: %s", type(response), response)
                    return ""
                if not response.content:
                    return ""
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
                logger.error("Unexpected error in complete() with model=%s: %s (type: %s)", model, e, type(e).__name__, exc_info=True)
                raise

        return ""

    async def ping(self) -> bool:
        """Lightweight availability check using the models list endpoint."""
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False
