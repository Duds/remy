"""
Base class for briefing generators.

Provides common utilities and dependency injection pattern for all briefing types.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...memory.goals import GoalStore
    from ...memory.plans import PlanStore
    from ...memory.facts import FactStore
    from ...memory.file_index import FileIndexer
    from ...google.calendar import CalendarClient
    from ...google.contacts import ContactsClient
    from ...ai.claude_client import ClaudeClient
    from ...analytics.analyzer import ConversationAnalyzer


class BriefingGenerator(ABC):
    """
    Abstract base class for briefing content generators.

    Subclasses implement `generate()` to produce briefing content.
    Dependencies are injected via constructor to enable testing and flexibility.
    """

    def __init__(
        self,
        user_id: int,
        goal_store: "GoalStore | None" = None,
        plan_store: "PlanStore | None" = None,
        fact_store: "FactStore | None" = None,
        calendar: "CalendarClient | None" = None,
        contacts: "ContactsClient | None" = None,
        file_indexer: "FileIndexer | None" = None,
        claude: "ClaudeClient | None" = None,
        conversation_analyzer: "ConversationAnalyzer | None" = None,
    ) -> None:
        self._user_id = user_id
        self._goal_store = goal_store
        self._plan_store = plan_store
        self._fact_store = fact_store
        self._calendar = calendar
        self._contacts = contacts
        self._file_indexer = file_indexer
        self._claude = claude
        self._conversation_analyzer = conversation_analyzer

    @abstractmethod
    async def generate(self) -> str:
        """Generate the briefing content. Returns empty string if nothing to report."""
        pass

    async def _get_active_goals(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch active goals for the user."""
        if not self._goal_store:
            return []
        return await self._goal_store.get_active(self._user_id, limit=limit)

    async def _get_stale_goals(self, days: int = 3) -> list[dict[str, Any]]:
        """Fetch goals not updated within N days."""
        if not self._goal_store:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        goals = await self._goal_store.get_active(self._user_id, limit=10)
        stale = []
        for g in goals:
            ts_str = g.get("updated_at") or g.get("created_at", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    stale.append(g)
            except ValueError:
                continue
        return stale

    def _format_date_header(self) -> str:
        """Return formatted date string for briefing headers."""
        return datetime.now(timezone.utc).strftime("%A, %d %B")
