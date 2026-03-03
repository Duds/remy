"""
Request timing utilities for per-phase latency tracking.

Provides a RequestTiming dataclass to accumulate timing across request phases,
and context managers for convenient instrumentation.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator


@dataclass
class RequestTiming:
    """
    Accumulates timing data across request processing phases.

    All times are in milliseconds. Phases:
    - validation_ms: Input validation and rate limiting
    - history_load_ms: Loading conversation history from storage
    - memory_injection_ms: Building context (facts, goals, embeddings)
    - ttft_ms: Time to first token from Claude API
    - tool_execution_ms: Total time spent executing tools
    - streaming_ms: Time from first token to stream completion
    - persistence_ms: Saving conversation turns to storage
    """

    validation_ms: int = 0
    history_load_ms: int = 0
    memory_injection_ms: int = 0
    ttft_ms: int = 0
    tool_execution_ms: int = 0
    streaming_ms: int = 0
    persistence_ms: int = 0

    def total_ms(self) -> int:
        """Return total request time across all phases."""
        return (
            self.validation_ms
            + self.history_load_ms
            + self.memory_injection_ms
            + self.ttft_ms
            + self.tool_execution_ms
            + self.streaming_ms
            + self.persistence_ms
        )


@contextmanager
def timed_phase(timing: RequestTiming, phase: str) -> Generator[None, None, None]:
    """
    Context manager that records elapsed time to a RequestTiming field.

    Usage:
        timing = RequestTiming()
        with timed_phase(timing, "memory_injection"):
            await build_context(...)
        # timing.memory_injection_ms is now set
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        setattr(timing, f"{phase}_ms", elapsed_ms)


class PhaseTimer:
    """
    Manual timer for phases that span non-contiguous code (e.g., TTFT).

    Usage:
        timer = PhaseTimer()
        timer.start()
        # ... do work ...
        timer.stop()
        timing.ttft_ms = timer.elapsed_ms
    """

    def __init__(self) -> None:
        self._start: float | None = None
        self._elapsed_ms: int = 0

    def start(self) -> None:
        """Start the timer."""
        self._start = time.monotonic()

    def stop(self) -> None:
        """Stop the timer and record elapsed time."""
        if self._start is not None:
            self._elapsed_ms = int((time.monotonic() - self._start) * 1000)
            self._start = None

    @property
    def elapsed_ms(self) -> int:
        """Return elapsed milliseconds (0 if not stopped)."""
        return self._elapsed_ms

    def add(self, ms: int) -> None:
        """Add milliseconds to the accumulated total (for multi-phase accumulation)."""
        self._elapsed_ms += ms
