"""
Telegram command and message handlers.

This package provides a modular structure for Telegram bot handlers.
All handlers acquire the per-user session lock before processing.

Tool-aware path: uses ClaudeClient.stream_with_tools() for native Anthropic
function calling. Claude autonomously decides when to invoke tools.

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
    get_task_timeout_seconds,
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
from .reactions import make_reaction_handler
from .callbacks import make_callback_handler
from ..handler_deps import CoreDeps, GoogleDeps, MemoryDeps, SchedulerDeps

if TYPE_CHECKING:
    from ..session import SessionManager
    from ...ai.tools import ToolRegistry
    from ...memory.database import DatabaseManager


def make_handlers(
    session_manager: "SessionManager",
    claude_client=None,
    db: "DatabaseManager | None" = None,
    tool_registry: "ToolRegistry | None" = None,
    memory_deps: MemoryDeps | None = None,
    google_deps: GoogleDeps | None = None,
    scheduler_deps: SchedulerDeps | None = None,
    core_deps: CoreDeps | None = None,
):
    """
    Factory that returns handler functions bound to shared dependencies.
    Register the returned handlers with the Telegram Application.

    This function composes handlers from all submodules into a single dict.
    """
    mem = memory_deps or MemoryDeps(conv_store=None)
    g = google_deps or GoogleDeps()
    sched = scheduler_deps or SchedulerDeps()
    core = core_deps or CoreDeps()

    handlers = {}

    # Core commands (start, help, cancel, status, setmychat, briefing)
    handlers.update(
        make_core_handlers(
            session_manager=session_manager,
            tool_registry=tool_registry,
            proactive_scheduler=sched.proactive_scheduler,
            scheduler_ref=sched.scheduler_ref,  # type: ignore[arg-type]
            automation_store=sched.automation_store,
        )
    )

    # File operations
    handlers.update(
        make_file_handlers(
            claude_client=claude_client,
            fact_store=mem.fact_store,
        )
    )

    # Gmail
    handlers.update(make_email_handlers(google_gmail=g.gmail))

    # Calendar
    handlers.update(make_calendar_handlers(google_calendar=g.calendar))

    # Contacts
    handlers.update(make_contacts_handlers(google_contacts=g.contacts))

    # Docs
    handlers.update(make_docs_handlers(google_docs=g.docs, claude_client=claude_client))

    # Web search, research, bookmarks, grocery
    handlers.update(
        make_web_handlers(
            claude_client=claude_client,
            fact_store=mem.fact_store,
            knowledge_store=mem.knowledge_store,
        )
    )

    # Memory and goals
    handlers.update(
        make_memory_handlers(
            session_manager=session_manager,
            conv_store=mem.conv_store,  # type: ignore[arg-type]
            claude_client=claude_client,
            goal_store=mem.goal_store,
            plan_store=mem.plan_store,
            job_store=sched.job_store,
            scheduler_ref=sched.scheduler_ref,  # type: ignore[arg-type]
        )
    )

    # Automations and Board
    handlers.update(
        make_automation_handlers(
            claude_client=claude_client,
            board_orchestrator=core.board_orchestrator,
            memory_injector=mem.memory_injector,
            automation_store=sched.automation_store,
            job_store=sched.job_store,
            agent_task_store=sched.agent_task_store,
            proactive_scheduler=sched.proactive_scheduler,
            scheduler_ref=sched.scheduler_ref,  # type: ignore[arg-type]
        )
    )

    # Chat handlers (message, voice, photo, document) — created before callback so we can pass run_attachment_vision
    chat_handlers_result = make_chat_handlers(
        session_manager=session_manager,
        conv_store=mem.conv_store,  # type: ignore[arg-type]
        claude_client=claude_client,
        knowledge_extractor=mem.knowledge_extractor,
        knowledge_store=mem.knowledge_store,
        memory_injector=mem.memory_injector,
        voice_transcriber=core.voice_transcriber,  # type: ignore[arg-type]
        db=db,
        tool_registry=tool_registry,
        google_gmail=g.gmail,
        diagnostics_runner=core.diagnostics_runner,  # type: ignore[arg-type]
        scheduler_ref=sched.scheduler_ref,  # type: ignore[arg-type]
        proactive_scheduler=sched.proactive_scheduler,
    )
    run_attachment_vision = chat_handlers_result.pop("_run_attachment_vision", None)
    handlers.update(chat_handlers_result)

    # Callback handler (inline Confirm/Cancel, suggested actions, snooze/done, run_auto, run_again, attach_act)
    handlers["callback"] = make_callback_handler(
        google_gmail=g.gmail,
        google_calendar=g.calendar,
        automation_store=sched.automation_store,
        scheduler_ref=sched.scheduler_ref,  # type: ignore[arg-type]
        claude_client=claude_client,
        tool_registry=tool_registry,
        session_manager=session_manager,
        conv_store=mem.conv_store,  # type: ignore[arg-type]
        db=db,
        board_orchestrator=core.board_orchestrator,
        job_store=sched.job_store,
        memory_injector=mem.memory_injector,
        run_research_flow=handlers.get("run_research_flow"),
        run_attachment_vision=run_attachment_vision,
    )

    # Admin and analytics (optional Anthropic Admin API for /costs)
    from ...config import settings
    from ...ai.anthropic_admin_client import AnthropicAdminClient

    admin_client = (
        AnthropicAdminClient(settings.anthropic_admin_api_key)
        if settings.anthropic_admin_api_key
        else None
    )
    handlers.update(
        make_admin_handlers(
            db=db,
            claude_client=claude_client,
            conversation_analyzer=core.conversation_analyzer,
            job_store=sched.job_store,
            diagnostics_runner=core.diagnostics_runner,  # type: ignore[arg-type]
            scheduler_ref=sched.scheduler_ref,  # type: ignore[arg-type]
            admin_client=admin_client,
        )
    )

    # Privacy audit
    handlers.update(
        make_privacy_handlers(
            session_manager=session_manager,
            conv_store=mem.conv_store,  # type: ignore[arg-type]
            claude_client=claude_client,
            tool_registry=tool_registry,
        )
    )

    # Emoji reaction handler
    handlers.update(
        make_reaction_handler(
            claude_client=claude_client,
            conv_store=mem.conv_store,  # type: ignore[arg-type]
            memory_injector=mem.memory_injector,
            session_manager=session_manager,
        )
    )

    return handlers


__all__ = [
    "make_handlers",
    "_build_message_from_turn",
    "_trim_messages_to_budget",
    "_TOOL_TURN_PREFIX",
    "_rate_limiter",
    "_task_start_times",
    "_pending_writes",
    "get_task_timeout_seconds",
]
