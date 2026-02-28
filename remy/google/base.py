"""
Base utilities for Google API clients.

Provides circuit breaker protection and retry logic with exponential backoff
for transient failures (rate limits, server errors).

Usage:
    from .base import with_google_resilience

    async def my_api_call():
        def _sync():
            return service.users().messages().list(...).execute()
        return await with_google_resilience("gmail", asyncio.to_thread(_sync))
"""

import asyncio
import logging
import random
from functools import wraps
from typing import Awaitable, Callable, TypeVar

from ..utils.circuit_breaker import CircuitOpenError, get_circuit_breaker

logger = logging.getLogger(__name__)

T = TypeVar("T")

# HTTP status codes that indicate transient failures worth retrying
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0


class GoogleAPIError(Exception):
    """Wrapper for Google API errors with status code."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _is_transient_error(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    try:
        from googleapiclient.errors import HttpError
        if isinstance(error, HttpError):
            return error.resp.status in TRANSIENT_STATUS_CODES
    except ImportError:
        pass

    error_str = str(error).lower()
    return any(indicator in error_str for indicator in [
        "rate limit", "quota", "503", "502", "504", "timeout",
        "connection reset", "connection refused", "temporarily unavailable",
    ])


def _get_retry_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """Calculate retry delay with exponential backoff and jitter."""
    delay = base_delay * (2 ** attempt)
    delay = min(delay, max_delay)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


async def with_retry(
    coro_factory: Callable[[], Awaitable[T]],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> T:
    """
    Execute an async operation with exponential backoff retry.

    Args:
        coro_factory: A callable that returns a new coroutine each time.
                     This is needed because coroutines can only be awaited once.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.

    Returns:
        The result of the successful operation.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except Exception as e:
            last_error = e

            if not _is_transient_error(e):
                logger.debug(
                    "Non-transient error (not retrying): %s",
                    e,
                )
                raise

            if attempt < max_retries - 1:
                delay = _get_retry_delay(attempt, base_delay, max_delay)
                logger.warning(
                    "Transient error on attempt %d/%d, retrying in %.1fs: %s",
                    attempt + 1, max_retries, delay, e,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d retry attempts exhausted: %s",
                    max_retries, e,
                )

    if last_error:
        raise last_error
    raise RuntimeError("Retry loop completed without result or error")


async def with_circuit_breaker(
    service_name: str,
    coro: Awaitable[T],
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> T:
    """
    Execute an async operation through a circuit breaker.

    Args:
        service_name: Name of the service (used for circuit breaker identification).
        coro: The coroutine to execute.
        failure_threshold: Number of failures before opening the circuit.
        recovery_timeout: Seconds to wait before attempting recovery.

    Returns:
        The result of the operation.

    Raises:
        CircuitOpenError: If the circuit is open.
        Any exception from the underlying operation.
    """
    breaker = get_circuit_breaker(
        f"google_{service_name}",
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )
    return await breaker.call(coro)


async def with_google_resilience(
    service_name: str,
    coro_factory: Callable[[], Awaitable[T]],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> T:
    """
    Execute a Google API call with full resilience: circuit breaker + retry.

    This is the recommended way to wrap Google API calls. It provides:
    1. Circuit breaker protection to fail fast when the service is down
    2. Exponential backoff retry for transient failures

    Args:
        service_name: Name of the Google service (e.g., "gmail", "calendar").
        coro_factory: A callable that returns a new coroutine each time.
        max_retries: Maximum retry attempts for transient failures.
        base_delay: Initial retry delay in seconds.
        failure_threshold: Circuit breaker failure threshold.
        recovery_timeout: Circuit breaker recovery timeout in seconds.

    Returns:
        The result of the successful API call.

    Raises:
        CircuitOpenError: If the circuit breaker is open.
        GoogleAPIError: For permanent API errors.
        Exception: For other unexpected errors.

    Example:
        async def get_emails():
            def _sync():
                return service.users().messages().list(userId="me").execute()
            return await with_google_resilience(
                "gmail",
                lambda: asyncio.to_thread(_sync)
            )
    """
    breaker = get_circuit_breaker(
        f"google_{service_name}",
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )

    async def _with_breaker() -> T:
        return await breaker.call(coro_factory())

    return await with_retry(
        _with_breaker,
        max_retries=max_retries,
        base_delay=base_delay,
    )


def resilient_google_call(
    service_name: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
):
    """
    Decorator to add Google API resilience to async methods.

    Usage:
        @resilient_google_call("gmail")
        async def get_unread(self, limit: int = 5) -> list[dict]:
            def _sync():
                return self._service().users().messages().list(...).execute()
            return await asyncio.to_thread(_sync)
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await with_google_resilience(
                service_name,
                lambda: func(*args, **kwargs),
                max_retries=max_retries,
                base_delay=base_delay,
            )
        return wrapper
    return decorator
