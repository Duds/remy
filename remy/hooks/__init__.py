"""Lifecycle hooks system for Remy.

Provides extensibility points throughout the message processing flow
without modifying core handlers.
"""

from remy.hooks.lifecycle import (
    HookContext,
    HookEvents,
    HookManager,
    hook_manager,
)

__all__ = [
    "HookContext",
    "HookEvents",
    "HookManager",
    "hook_manager",
]
