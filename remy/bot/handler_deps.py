"""
Handler dependency containers — reduces make_handlers() parameter count.

Groups related dependencies so make_handlers() takes < 8 parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..memory.conversations import ConversationStore
    from ..memory.facts import FactStore
    from ..memory.goals import GoalStore
    from ..memory.injector import MemoryInjector
    from ..memory.knowledge import KnowledgeStore
    from ..memory.plans import PlanStore
    from ..memory.automations import AutomationStore
    from ..memory.background_jobs import BackgroundJobStore
    from ..memory.counters import CounterStore
    from ..agents.agent_task_lifecycle import AgentTaskStore
    from ..scheduler.proactive import ProactiveScheduler
    from ..google.calendar import CalendarClient
    from ..google.gmail import GmailClient
    from ..google.docs import DocsClient
    from ..google.contacts import ContactsClient
    from ..agents.orchestrator import BoardOrchestrator
    from ..analytics.analyzer import ConversationAnalyzer


@dataclass(frozen=False)
class MemoryDeps:
    """Memory-related dependencies for handlers."""

    conv_store: "ConversationStore | None" = None
    knowledge_extractor: Any = None
    knowledge_store: "KnowledgeStore | None" = None
    fact_store: "FactStore | None" = None
    goal_store: "GoalStore | None" = None
    memory_injector: "MemoryInjector | None" = None
    plan_store: "PlanStore | None" = None


@dataclass(frozen=False)
class GoogleDeps:
    """Google Workspace clients for handlers."""

    calendar: "CalendarClient | None" = None
    gmail: "GmailClient | None" = None
    docs: "DocsClient | None" = None
    contacts: "ContactsClient | None" = None


@dataclass(frozen=False)
class SchedulerDeps:
    """Scheduler and automation dependencies for handlers."""

    proactive_scheduler: "ProactiveScheduler | None" = None
    scheduler_ref: dict | None = None
    automation_store: "AutomationStore | None" = None
    counter_store: "CounterStore | None" = None
    job_store: "BackgroundJobStore | None" = None
    agent_task_store: "AgentTaskStore | None" = None


@dataclass(frozen=False)
class CoreDeps:
    """Core handler dependencies (board, voice, analytics, diagnostics)."""

    board_orchestrator: "BoardOrchestrator | None" = None
    voice_transcriber: Any = None
    conversation_analyzer: "ConversationAnalyzer | None" = None
    diagnostics_runner: Any = None
