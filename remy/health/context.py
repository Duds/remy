"""Injectable context for health server routes. Replaces set_* globals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..memory.database import DatabaseManager


@dataclass
class HealthContext:
    """Injectable dependencies for health server routes. Replaces set_* globals."""

    diagnostics_runner: Any = None
    outbound_queue: Any = None
    hook_manager: Any = None
    db: "DatabaseManager | None" = None
    data_dir: str = "./data"
    webhook_manager: Any = None
    # Incoming webhook
    incoming_bot: Any = None
    incoming_get_chat_id: Callable[[], int | None] | None = None
    incoming_automation_store: Any = None
    incoming_webhook_user_id: int | None = None
    # Rate limiting for incoming webhooks (ip -> list of timestamps)
    incoming_webhook_rate: dict[str, list[float]] = field(default_factory=dict)
    incoming_webhook_rate_limit: int = 60
    # Ready flag (mutable)
    _ready: bool = False

    def set_ready(self) -> None:
        """Mark the server as ready (database and scheduler initialised)."""
        object.__setattr__(self, "_ready", True)

    def is_ready(self) -> bool:
        """Return whether the server is marked ready."""
        return self._ready
