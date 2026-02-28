"""
Google Workspace integration package.
Requires setup via scripts/setup_google_auth.py before use.

All Google API clients use circuit breaker protection and exponential backoff
retry for transient failures. See base.py for implementation details.
"""

from .base import (
    GoogleAPIError,
    with_google_resilience,
    with_retry,
    with_circuit_breaker,
    resilient_google_call,
)

__all__ = [
    "GoogleAPIError",
    "with_google_resilience",
    "with_retry",
    "with_circuit_breaker",
    "resilient_google_call",
]
