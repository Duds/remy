"""
Circuit breaker pattern for API resilience.

Prevents cascading failures by temporarily blocking calls to failing services.
After a threshold of failures, the circuit "opens" and fails fast for a recovery
period before allowing test requests through.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failing fast, no requests allowed
- HALF_OPEN: Testing if service recovered, limited requests allowed
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when circuit is open and request is blocked."""
    
    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit '{name}' is open. Retry after {retry_after:.1f}s")


@dataclass
class CircuitBreaker:
    """
    Circuit breaker with configurable thresholds.
    
    Usage:
        breaker = CircuitBreaker(name="anthropic", failure_threshold=5)
        
        try:
            result = await breaker.call(api_call())
        except CircuitOpenError:
            # Use fallback or fail fast
            pass
    """
    
    name: str
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: float = 60.0  # Seconds before trying again
    half_open_max_calls: int = 3  # Test calls in half-open state
    
    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    # Stats tracking (for diagnostics)
    _total_calls: int = field(default=0, init=False)
    _total_successes: int = field(default=0, init=False)
    _total_failures: int = field(default=0, init=False)
    _total_blocked: int = field(default=0, init=False)
    _last_success_time: float = field(default=0.0, init=False)
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    @property
    def is_closed(self) -> bool:
        """True if circuit is allowing requests."""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """True if circuit is blocking requests."""
        return self._state == CircuitState.OPEN
    
    def _time_since_last_failure(self) -> float:
        """Seconds since the last recorded failure."""
        if self._last_failure_time == 0:
            return float("inf")
        return time.monotonic() - self._last_failure_time
    
    async def _check_state_transition(self) -> None:
        """Check if state should transition based on time."""
        if self._state == CircuitState.OPEN:
            if self._time_since_last_failure() >= self.recovery_timeout:
                logger.info(
                    "Circuit '%s' transitioning from OPEN to HALF_OPEN",
                    self.name
                )
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
    
    async def call(self, coro: Awaitable[T]) -> T:
        """
        Execute a coroutine through the circuit breaker.
        
        Raises CircuitOpenError if the circuit is open.
        Records failures and successes to manage state transitions.
        """
        async with self._lock:
            self._total_calls += 1
            await self._check_state_transition()
            
            if self._state == CircuitState.OPEN:
                self._total_blocked += 1
                retry_after = self.recovery_timeout - self._time_since_last_failure()
                raise CircuitOpenError(self.name, max(0, retry_after))
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self._total_blocked += 1
                    # Too many test calls, stay in half-open but block
                    raise CircuitOpenError(self.name, self.recovery_timeout / 2)
                self._half_open_calls += 1
        
        try:
            result = await coro
            await self._record_success()
            return result
        except Exception as e:
            await self._record_failure(e)
            raise
    
    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._total_successes += 1
            self._last_success_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit '%s' transitioning from HALF_OPEN to CLOSED",
                    self.name
                )
                self._state = CircuitState.CLOSED
                self._failure_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    async def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_time = time.monotonic()
            
            logger.warning(
                "Circuit '%s' recorded failure %d/%d: %s",
                self.name, self._failure_count, self.failure_threshold, error
            )
            
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                logger.warning(
                    "Circuit '%s' transitioning from HALF_OPEN to OPEN",
                    self.name
                )
                self._state = CircuitState.OPEN
            elif self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Circuit '%s' transitioning from CLOSED to OPEN",
                    self.name
                )
                self._state = CircuitState.OPEN
    
    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._half_open_calls = 0
        logger.info("Circuit '%s' manually reset to CLOSED", self.name)

    def get_stats(self) -> dict:
        """Get statistics for this circuit breaker."""
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "total_calls": self._total_calls,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "total_blocked": self._total_blocked,
            "last_failure_time": self._last_failure_time if self._last_failure_time > 0 else None,
            "last_success_time": self._last_success_time if self._last_success_time > 0 else None,
            "success_rate": (
                round(self._total_successes / self._total_calls * 100, 1)
                if self._total_calls > 0 else None
            ),
        }


# Global circuit breakers for common services
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """
    Get or create a circuit breaker for a named service.
    
    Circuit breakers are cached by name, so multiple calls with the same
    name return the same instance.
    """
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _circuit_breakers[name]


def reset_all_circuits() -> None:
    """Reset all circuit breakers to closed state."""
    for breaker in _circuit_breakers.values():
        breaker.reset()


def get_all_circuit_states() -> dict[str, dict]:
    """
    Return state and stats for all circuit breakers.
    
    Used by the /diagnostics endpoint to expose circuit breaker health.
    """
    return {
        name: breaker.get_stats()
        for name, breaker in _circuit_breakers.items()
    }


def get_circuit_summary() -> dict:
    """
    Return a summary of all circuit breakers for quick health assessment.
    """
    states = get_all_circuit_states()
    
    open_circuits = [
        name for name, stats in states.items()
        if stats["state"] == "open"
    ]
    half_open_circuits = [
        name for name, stats in states.items()
        if stats["state"] == "half_open"
    ]
    
    total_calls = sum(s["total_calls"] for s in states.values())
    total_blocked = sum(s["total_blocked"] for s in states.values())
    
    return {
        "total_circuits": len(states),
        "open_circuits": open_circuits,
        "half_open_circuits": half_open_circuits,
        "all_healthy": len(open_circuits) == 0 and len(half_open_circuits) == 0,
        "total_calls": total_calls,
        "total_blocked": total_blocked,
        "circuits": states,
    }
