"""
Briefing generators for proactive scheduler messages.

Each generator produces a specific type of briefing content (morning, afternoon,
evening, retrospective) and can be tested independently of the scheduler.
"""

from .base import BriefingGenerator
from .morning import MorningBriefingGenerator
from .afternoon import AfternoonFocusGenerator
from .evening import EveningCheckinGenerator
from .retrospective import MonthlyRetrospectiveGenerator

__all__ = [
    "BriefingGenerator",
    "MorningBriefingGenerator",
    "AfternoonFocusGenerator",
    "EveningCheckinGenerator",
    "MonthlyRetrospectiveGenerator",
]
