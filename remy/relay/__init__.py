"""
Relay client for inter-agent communication with cowork.

Writes directly to the relay SQLite database (shared with relay_mcp server).
Used when Remy needs to post messages or notes to cowork from Python code
(e.g. [Send to cowork] callback) without going through MCP.
"""

from __future__ import annotations

from .client import post_message_to_cowork, post_note, get_messages_for_remy, get_tasks_for_remy

__all__ = ["post_message_to_cowork", "post_note", "get_messages_for_remy", "get_tasks_for_remy"]
