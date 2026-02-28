"""
Evening check-in generator.

Produces the evening nudge about goals that haven't been mentioned recently.
"""

import logging

from .base import BriefingGenerator

logger = logging.getLogger(__name__)

_STALE_GOAL_DAYS = 3


class EveningCheckinGenerator(BriefingGenerator):
    """
    Generates the evening check-in content.

    Includes:
    - Goals not updated within the stale threshold (default 3 days)

    Returns empty string if no stale goals, indicating no message should be sent.
    """

    def __init__(self, *args, stale_days: int = _STALE_GOAL_DAYS, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stale_days = stale_days

    async def generate(self) -> str:
        """Generate the evening check-in content. Returns empty if no stale goals."""
        stale_goals = await self._get_stale_goals(days=self._stale_days)
        if not stale_goals:
            logger.debug("Evening check-in: no stale goals, skipping")
            return ""

        stale_lines = [f"• *{g['title']}*" for g in stale_goals]
        goals_text = "\n".join(stale_lines)

        return (
            f"🌙 *Evening check-in*\n\n"
            f"You haven't mentioned these goals in a while:\n{goals_text}\n\n"
            f"Still working on them? Let me know how it's going."
        )
