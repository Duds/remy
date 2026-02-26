"""Custom exception hierarchy for drbot."""


class DrbotError(Exception):
    """Base exception for all drbot errors."""


class ServiceUnavailableError(DrbotError):
    """Raised when all AI backends are unavailable."""


class MemoryError(DrbotError):
    """Raised on storage read/write failures."""


class SessionError(DrbotError):
    """Raised on session management failures."""


class CancelledError(DrbotError):
    """Raised when a user cancels an in-progress task."""
