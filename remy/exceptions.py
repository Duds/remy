"""Custom exception hierarchy for remy."""


class RemyError(Exception):
    """Base exception for Remy applications."""
    pass


class ServiceUnavailableError(RemyError):
    """Raised when an external service (e.g. Anthropic, Telegram) is down."""
    pass


class StorageError(RemyError):
    """Raised when there's an issue with SQLite or vector storage."""
    pass


# Backwards compatibility alias (deprecated: use StorageError instead)
# Note: This shadows the builtin MemoryError, which was the reason for renaming.
MemoryError = StorageError


class SessionError(RemyError):
    """Raised when session state is corrupted or missing."""
    pass


class CancelledError(RemyError):
    """Raised when an operation is explicitly cancelled by the user."""
    pass
