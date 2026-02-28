"""Lifecycle hook system for extensibility.

Inspired by OpenClaw's hook architecture, this provides typed hook points
throughout the message processing flow for logging, metrics, transformations,
and debugging without modifying core handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class HookEvents(str, Enum):
    """Lifecycle events that can trigger hooks."""

    SESSION_START = "session_start"
    BEFORE_MODEL_RESOLVE = "before_model_resolve"
    BEFORE_PROMPT_BUILD = "before_prompt_build"
    LLM_INPUT = "llm_input"
    LLM_OUTPUT = "llm_output"
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    MESSAGE_SENDING = "message_sending"
    SESSION_END = "session_end"
    BEFORE_COMPACTION = "before_compaction"
    AFTER_COMPACTION = "after_compaction"


@dataclass
class HookContext:
    """Context passed to hook handlers.

    Handlers can modify the data dict to transform values flowing through
    the pipeline, or set cancelled=True to abort processing.
    """

    event: HookEvents
    data: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    modifications: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def modify(self, key: str, value: Any) -> None:
        """Record a modification to the context data."""
        self.data[key] = value
        self.modifications.append(key)


HookHandler = Callable[[HookContext], Coroutine[Any, Any, HookContext]]


@dataclass
class HookStats:
    """Statistics for hook emissions."""

    total_emissions: int = 0
    emissions_by_event: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_emission_time: datetime | None = None
    total_handlers_invoked: int = 0
    total_duration_ms: float = 0.0


class HookManager:
    """Manages lifecycle hooks registration and emission.

    Thread-safe singleton that coordinates hook handlers across the application.
    """

    def __init__(self) -> None:
        self._hooks: dict[HookEvents, list[HookHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._stats = HookStats()

    def register(self, event: HookEvents, handler: HookHandler) -> None:
        """Register a handler for a lifecycle event.

        Args:
            event: The event to listen for.
            handler: Async function that receives and returns HookContext.
        """
        self._hooks[event].append(handler)
        logger.debug("Registered hook handler for %s", event.value)

    def unregister(self, event: HookEvents, handler: HookHandler) -> bool:
        """Remove a handler from an event.

        Returns:
            True if handler was found and removed, False otherwise.
        """
        try:
            self._hooks[event].remove(handler)
            logger.debug("Unregistered hook handler for %s", event.value)
            return True
        except ValueError:
            return False

    def on(self, event: HookEvents) -> Callable[[HookHandler], HookHandler]:
        """Decorator to register a hook handler.

        Usage:
            @hook_manager.on(HookEvents.LLM_OUTPUT)
            async def log_tokens(context: HookContext) -> HookContext:
                logger.info("Tokens: %s", context.data.get("output_tokens"))
                return context
        """

        def decorator(handler: HookHandler) -> HookHandler:
            self.register(event, handler)
            return handler

        return decorator

    async def emit(
        self,
        event: HookEvents,
        data: dict[str, Any] | None = None,
    ) -> HookContext:
        """Emit a lifecycle event and run all registered handlers.

        Handlers are run sequentially in registration order. Each handler
        receives the context returned by the previous handler, allowing
        transformations to chain.

        Args:
            event: The event being emitted.
            data: Initial data for the context.

        Returns:
            The final HookContext after all handlers have run.
        """
        context = HookContext(event=event, data=data or {})
        handlers = self._hooks.get(event, [])

        start_time = time.perf_counter()

        async with self._lock:
            self._stats.total_emissions += 1
            self._stats.emissions_by_event[event.value] += 1
            self._stats.last_emission_time = datetime.now(timezone.utc)

        for handler in handlers:
            if context.cancelled:
                logger.debug("Hook chain cancelled at %s", event.value)
                break

            try:
                context = await handler(context)
                async with self._lock:
                    self._stats.total_handlers_invoked += 1
            except Exception:
                logger.exception("Hook handler failed for %s", event.value)

        duration_ms = (time.perf_counter() - start_time) * 1000
        async with self._lock:
            self._stats.total_duration_ms += duration_ms

        if handlers:
            logger.debug(
                "Emitted %s to %d handlers in %.2fms",
                event.value,
                len(handlers),
                duration_ms,
            )

        return context

    def get_registered_count(self) -> int:
        """Return total number of registered handlers."""
        return sum(len(handlers) for handlers in self._hooks.values())

    def get_stats(self) -> dict[str, Any]:
        """Return hook statistics for diagnostics."""
        return {
            "registered_handlers": self.get_registered_count(),
            "total_emissions": self._stats.total_emissions,
            "emissions_by_event": dict(self._stats.emissions_by_event),
            "total_handlers_invoked": self._stats.total_handlers_invoked,
            "total_duration_ms": round(self._stats.total_duration_ms, 2),
            "last_emission": (
                self._stats.last_emission_time.isoformat()
                if self._stats.last_emission_time
                else None
            ),
        }

    def clear(self) -> None:
        """Remove all registered handlers. Useful for testing."""
        self._hooks.clear()
        logger.debug("Cleared all hook handlers")


hook_manager = HookManager()
