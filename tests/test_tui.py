"""
Tests for Remy TUI (US-terminal-ui).
"""

import re

from remy.bot.session import SessionManager
from remy.tui.runner import TUI_USER_ID


def test_tui_user_id_constant() -> None:
    """TUI uses a fixed user id so session is separate from Telegram."""
    assert TUI_USER_ID == 0


def test_tui_session_key_format() -> None:
    """TUI session key is user_0_YYYYMMDD (daily, no thread)."""
    key = SessionManager.get_session_key(TUI_USER_ID, None)
    assert key.startswith("user_0_")
    assert re.match(r"^user_0_\d{8}$", key), f"Expected user_0_YYYYMMDD, got {key!r}"
