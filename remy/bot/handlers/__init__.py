"""
Telegram command and message handlers.

This package provides a modular structure for Telegram bot handlers.
All handlers acquire the per-user session lock before processing.

Two processing paths for text input:
  - Tool-aware path (preferred): uses ClaudeClient.stream_with_tools() for
    native Anthropic function calling. Claude autonomously decides when to
    invoke get_logs, get_goals, get_facts, run_board, or check_status.
  - Router fallback: used when tool_registry is not available.

Modules:
  - base: Core utilities, auth checks, message building
  - core: Start, help, cancel, status commands
  - files: File operations (read, write, ls, find, organize)
  - email: Gmail commands
  - calendar: Google Calendar commands
  - contacts: Google Contacts commands
  - docs: Google Docs commands
  - web: Web search, research, bookmarks, grocery list
  - memory: Goals, plans, conversation management
  - automations: Scheduled reminders, task breakdown, Board
  - admin: Diagnostics, stats, logs, costs
  - privacy: Privacy audit
  - chat: Main message handler, voice, photo, document
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import (
    _build_message_from_turn,
    _trim_messages_to_budget,
    _TOOL_TURN_PREFIX,
    _rate_limiter,
    _task_start_times,
    _pending_writes,
    _pending_archive,
    TASK_TIMEOUT_SECONDS,
)
from .core import make_core_handlers
from .files import make_file_handlers
from .email import make_email_handlers
from .calendar import make_calendar_handlers
from .contacts import make_contacts_handlers
from .docs import make_docs_handlers
from .web import make_web_handlers
from .memory import make_memory_handlers
from .automations import make_automation_handlers
from .admin import make_admin_handlers
from .privacy import make_privacy_handlers
from .chat import make_chat_handlers

if TYPE_CHECKING:
    from ..session import SessionManager
    from ...ai.router import ModelRouter
    from ...ai.tool_registry import ToolRegistry
    from ...memory.conversations import ConversationStore
    from ...memory.facts import FactExtractor, FactStore
    from ...memory.goals import GoalExtractor, GoalStore
    from ...memory.injector import MemoryInjector
    from ...memory.automations import AutomationStore
    from ...memory.background_jobs import BackgroundJobStore
    from ...memory.plans import PlanStore
    from ...memory.database import DatabaseManager
    from ...agents.orchestrator import BoardOrchestrator
    from ...scheduler.proactive import ProactiveScheduler
    from ...analytics.analyzer import ConversationAnalyzer
    from ...voice.transcriber import VoiceTranscriber
    from ...google.calendar import CalendarClient
    from ...google.gmail import GmailClient
    from ...google.docs import DocsClient
    from ...google.contacts import ContactsClient
    from ...diagnostics import DiagnosticsRunner


def make_handlers(
    session_manager: "SessionManager",
    router: "ModelRouter",
    conv_store: "ConversationStore",
    claude_client=None,
    fact_extractor: "FactExtractor | None" = None,
    fact_store: "FactStore | None" = None,
    goal_extractor: "GoalExtractor | None" = None,
    goal_store: "GoalStore | None" = None,
    memory_injector: "MemoryInjector | None" = None,
    voice_transcriber: "VoiceTranscriber | None" = None,
    proactive_scheduler: "ProactiveScheduler | None" = None,
    board_orchestrator: "BoardOrchestrator | None" = None,
    db: "DatabaseManager | None" = None,
    tool_registry: "ToolRegistry | None" = None,
    google_calendar: "CalendarClient | None" = None,
    google_gmail: "GmailClient | None" = None,
    google_docs: "DocsClient | None" = None,
    google_contacts: "ContactsClient | None" = None,
    automation_store: "AutomationStore | None" = None,
    scheduler_ref: dict | None = None,
    conversation_analyzer: "ConversationAnalyzer | None" = None,
    job_store: "BackgroundJobStore | None" = None,
    plan_store: "PlanStore | None" = None,
    diagnostics_runner: "DiagnosticsRunner | None" = None,
):
    """
    Factory that returns handler functions bound to shared dependencies.
    Register the returned handlers with the Telegram Application.
    
    This function composes handlers from all submodules into a single dict.
    """
    handlers = {}

    # Core commands (start, help, cancel, status, setmychat, briefing)
    handlers.update(make_core_handlers(
        session_manager=session_manager,
        tool_registry=tool_registry,
        proactive_scheduler=proactive_scheduler,
        scheduler_ref=scheduler_ref,
    ))

    # File operations
    handlers.update(make_file_handlers(
        claude_client=claude_client,
        fact_store=fact_store,
    ))

    # Gmail
    handlers.update(make_email_handlers(
        google_gmail=google_gmail,
    ))

    # Calendar
    handlers.update(make_calendar_handlers(
        google_calendar=google_calendar,
    ))

    # Contacts
    handlers.update(make_contacts_handlers(
        google_contacts=google_contacts,
    ))

    # Docs
    handlers.update(make_docs_handlers(
        google_docs=google_docs,
        claude_client=claude_client,
    ))

    # Web search, research, bookmarks, grocery
    handlers.update(make_web_handlers(
        claude_client=claude_client,
        fact_store=fact_store,
    ))

    # Memory and goals
    handlers.update(make_memory_handlers(
        session_manager=session_manager,
        conv_store=conv_store,
        claude_client=claude_client,
        goal_store=goal_store,
        plan_store=plan_store,
        job_store=job_store,
        scheduler_ref=scheduler_ref,
    ))

    # Automations and Board
    handlers.update(make_automation_handlers(
        claude_client=claude_client,
        board_orchestrator=board_orchestrator,
        memory_injector=memory_injector,
        automation_store=automation_store,
        job_store=job_store,
        proactive_scheduler=proactive_scheduler,
        scheduler_ref=scheduler_ref,
    ))

    # Admin and analytics
    handlers.update(make_admin_handlers(
        db=db,
        claude_client=claude_client,
        conversation_analyzer=conversation_analyzer,
        job_store=job_store,
        diagnostics_runner=diagnostics_runner,
        scheduler_ref=scheduler_ref,
    ))

    # Privacy audit
    handlers.update(make_privacy_handlers(
        session_manager=session_manager,
        conv_store=conv_store,
        claude_client=claude_client,
        tool_registry=tool_registry,
    ))

    # Chat handlers (message, voice, photo, document)
    handlers.update(make_chat_handlers(
        session_manager=session_manager,
        router=router,
        conv_store=conv_store,
        claude_client=claude_client,
        fact_extractor=fact_extractor,
        fact_store=fact_store,
        goal_extractor=goal_extractor,
        goal_store=goal_store,
        memory_injector=memory_injector,
        voice_transcriber=voice_transcriber,
        db=db,
        tool_registry=tool_registry,
        google_gmail=google_gmail,
        diagnostics_runner=diagnostics_runner,
        scheduler_ref=scheduler_ref,
        proactive_scheduler=proactive_scheduler,
    ))

    return handlers


__all__ = [
    "make_handlers",
    "_build_message_from_turn",
    "_trim_messages_to_budget",
    "_TOOL_TURN_PREFIX",
]
