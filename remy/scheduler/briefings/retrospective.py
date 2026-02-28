"""
Monthly retrospective generator.

Produces the end-of-month summary using Claude to synthesise conversation history.
"""

import logging

from .base import BriefingGenerator

logger = logging.getLogger(__name__)


class MonthlyRetrospectiveGenerator(BriefingGenerator):
    """
    Generates the monthly retrospective content.

    Uses the conversation analyser to generate a Claude-synthesised summary
    of the month's conversations and progress.

    Returns empty string if required dependencies are not configured.
    """

    async def generate(self) -> str:
        """Generate the monthly retrospective content."""
        if self._conversation_analyzer is None:
            logger.debug("Monthly retrospective skipped — analytics not configured")
            return ""

        if self._claude is None:
            logger.debug("Monthly retrospective skipped — Claude not configured")
            return ""

        try:
            retro = await self._conversation_analyzer.generate_retrospective(
                self._user_id, "month", self._claude
            )
            if len(retro) > 4000:
                retro = retro[:4000] + "…"
            return retro
        except Exception as e:
            logger.error("Monthly retrospective generation failed: %s", e)
            return ""
