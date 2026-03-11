"""
Claude Agent SDK integration (US-claude-agent-sdk-subagents, US-claude-agent-sdk-migration).

Legacy stub: board and research now use remy.agents.sdk_subagents (run_board_analyst,
run_deep_researcher). This module is kept for backwards compatibility; new code should
use sdk_subagents.is_sdk_available() and the runners there.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_sdk_available() -> bool:
    """Return True if claude-agent-sdk is installed. Prefer sdk_subagents.is_sdk_available()."""
    try:
        import claude_agent_sdk  # noqa: F401
        return True
    except ImportError:
        return False


async def run_research_via_sdk(topic: str, **_kwargs: Any) -> str | None:
    """
    Run research via SDK. Deprecated: use sdk_subagents.run_deep_researcher() with
    tool_registry instead.
    """
    from . import sdk_subagents

    if not sdk_subagents.is_sdk_available():
        return None
    # Caller does not pass tool_registry; we cannot run without it
    return None
