"""
Self-diagnostics suite for Remy.

Provides comprehensive health checks for all subsystems including database,
memory/embeddings, AI providers, scheduler, and configuration.

Trigger phrase: "Are you there, God. It's me Dale."
"""

import re

from .runner import DiagnosticsRunner, CheckResult, CheckStatus, format_diagnostics_output
from .logs import (
    get_error_summary,
    get_recent_logs,
    get_session_start,
    get_session_start_line,
    since_dt,
    _since_dt,
)

# Trigger phrase regex — case-insensitive, punctuation-flexible
# Matches: "Are you there, God. It's me Dale."
# And variations like: "Are you there God? Its me, Dale"
DIAGNOSTICS_TRIGGER = re.compile(
    r"are you there[,\s]*god[.?\s]*it'?s me[,\s]*dale\.?",
    re.IGNORECASE
)


def is_diagnostics_trigger(text: str) -> bool:
    """Check if text matches the diagnostics trigger phrase."""
    return bool(DIAGNOSTICS_TRIGGER.search(text))


__all__ = [
    "DiagnosticsRunner",
    "CheckResult",
    "CheckStatus",
    "format_diagnostics_output",
    "is_diagnostics_trigger",
    "DIAGNOSTICS_TRIGGER",
    "get_error_summary",
    "get_recent_logs",
    "get_session_start",
    "get_session_start_line",
    "since_dt",
    "_since_dt",
]
