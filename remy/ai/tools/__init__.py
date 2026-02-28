"""
Tool registry package for native Anthropic tool use (function calling).

This package provides the ToolRegistry class and TOOL_SCHEMAS for exposing
slash-command functionality to Claude via natural language.

The package is organised into domain-specific modules:
- schemas.py: Tool schema definitions (Anthropic ToolParam format)
- registry.py: ToolRegistry class and dispatch logic
- time.py: Time/date executors
- memory.py: Memory, goals, facts executors
- calendar.py: Google Calendar executors
- email.py: Gmail executors
- contacts.py: Google Contacts executors
- files.py: File system executors
- web.py: Web search executors
- automations.py: Reminders and automation executors
- plans.py: Plan tracking executors
- analytics.py: Analytics and stats executors
- docs.py: Google Docs executors
- bookmarks.py: Bookmark executors
- projects.py: Project tracking executors
- session.py: Session, privacy, and special executors

Re-exports:
    ToolRegistry: Main class for dispatching tool calls
    TOOL_SCHEMAS: List of Anthropic tool schemas
"""

from .registry import ToolRegistry
from .schemas import TOOL_SCHEMAS

__all__ = ["ToolRegistry", "TOOL_SCHEMAS"]
