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


class SessionError(RemyError):
    """Raised when session state is corrupted or missing."""
    pass


class CancelledError(RemyError):
    """Raised when an operation is explicitly cancelled by the user."""
    pass


class ToolExecutionError(RemyError):
    """Raised when a tool executor fails (e.g. API error, validation)."""
    pass


class RateLimitError(RemyError):
    """Raised when rate limit is exceeded."""
    pass


class ValidationError(RemyError):
    """Raised when input validation fails."""
    pass
