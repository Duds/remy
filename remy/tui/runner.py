"""
TUI pipeline runner — builds the same dependency graph as main.py (no Telegram/health)
and runs one chat turn via stream_with_tools + persistence (US-terminal-ui).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from ..memory.injector import MemoryInjector

from ..ai.claude_client import ClaudeClient, StreamEvent
from ..bot.session import SessionManager
from ..config import settings
from ..memory.conversations import ConversationStore

logger = logging.getLogger(__name__)

# Fixed user id for TUI — session key is user_0_YYYYMMDD (separate from Telegram).
TUI_USER_ID = 0


@dataclass
class TUIDeps:
    """Dependencies for TUI chat — same as main.py up to (not including) Telegram bot."""

    conv_store: ConversationStore
    session_manager: SessionManager
    claude_client: ClaudeClient
    tool_registry: object  # ToolRegistry
    memory_injector: MemoryInjector | None
    settings: object  # Settings


async def build_tui_deps() -> TUIDeps:
    """
    Build the same object graph as main.py for the chat pipeline, without
    Telegram bot, health server, or proactive scheduler.
    """
    from ..logging_config import setup_logging

    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.sessions_dir, exist_ok=True)
    os.makedirs(settings.logs_dir, exist_ok=True)
    setup_logging(settings.log_level, settings.logs_dir, settings.azure_environment)

    from ..memory.database import DatabaseManager
    from ..memory.embeddings import EmbeddingStore
    from ..memory.facts import FactStore
    from ..memory.fts import FTSSearch
    from ..memory.goals import GoalStore
    from ..memory.knowledge import KnowledgeExtractor, KnowledgeStore
    from ..memory.counters import CounterStore
    from ..memory.automations import AutomationStore
    from ..memory.background_jobs import BackgroundJobStore
    from ..memory.plans import PlanStore
    from ..analytics.analyzer import ConversationAnalyzer
    from ..agents.orchestrator import BoardOrchestrator
    from ..ai.tools import ToolRegistry
    from ..ai.tools.context import ToolContext
    from ..memory.injector import MemoryInjector
    from ..ai.tone import ToneDetector
    from ..delivery import OutboundQueue
    from ..startup_context import StartupContext
    from ..memory.file_index import FileIndexer

    db = DatabaseManager()
    await db.init()

    session_manager = SessionManager()
    conv_store = ConversationStore(settings.sessions_dir)
    claude_client = ClaudeClient()

    embeddings = EmbeddingStore(db)
    fact_store = FactStore(db, embeddings)
    goal_store = GoalStore(db, embeddings)
    fts = FTSSearch(db)
    knowledge_store = KnowledgeStore(db, embeddings)
    knowledge_extractor = KnowledgeExtractor(claude_client)
    tone_detector = ToneDetector(
        knowledge_store=knowledge_store,
        embeddings=embeddings,
        claude_client=claude_client,
    )
    counter_store = CounterStore(db)
    memory_injector = MemoryInjector(
        db, embeddings, knowledge_store, fts, tone_detector, counter_store=counter_store
    )
    automation_store = AutomationStore(db)
    job_store = BackgroundJobStore(db)
    plan_store = PlanStore(db)
    conv_analyzer = ConversationAnalyzer(conv_store, db)

    _base_rag_paths = (
        [p.strip() for p in settings.rag_index_paths.split(",") if p.strip()]
        if settings.rag_index_paths
        else [str(Path.home() / "Projects"), str(Path.home() / "Documents")]
    )
    _base_rag_paths = [str(Path(p).expanduser()) for p in _base_rag_paths]
    _all_index_paths = _base_rag_paths + list(settings.gdrive_mount_paths)
    file_indexer = FileIndexer(
        db=db,
        embeddings=embeddings,
        index_paths=_all_index_paths if _all_index_paths else None,
        index_extensions=(
            {e.strip() for e in settings.rag_index_extensions.split(",") if e.strip()}
            if settings.rag_index_extensions
            else None
        ),
        enabled=settings.rag_index_enabled,
    )

    outbound_queue = OutboundQueue(db_path=db.db_path, bot=None)
    startup_ctx = StartupContext(outbound_queue=outbound_queue)
    board_orchestrator = BoardOrchestrator(claude_client)

    from ..ai.mistral_client import MistralClient
    from ..ai.moonshot_client import MoonshotClient

    mistral_client = MistralClient()
    moonshot_client = MoonshotClient()

    tool_ctx = ToolContext(
        logs_dir=settings.logs_dir,
        knowledge_store=knowledge_store,
        knowledge_extractor=knowledge_extractor,
        board_orchestrator=board_orchestrator,
        claude_client=claude_client,
        mistral_client=mistral_client,
        moonshot_client=moonshot_client,
        ollama_base_url=settings.ollama_base_url,
        model_complex=settings.model_complex,
        calendar_client=None,
        gmail_client=None,
        contacts_client=None,
        docs_client=None,
        automation_store=automation_store,
        scheduler_ref=startup_ctx,  # type: ignore[arg-type]
        conversation_analyzer=conv_analyzer,
        job_store=job_store,
        plan_store=plan_store,
        file_indexer=file_indexer,
        fact_store=fact_store,
        goal_store=goal_store,
        counter_store=counter_store,
    )
    tool_registry = ToolRegistry(tool_ctx)

    return TUIDeps(
        conv_store=conv_store,
        session_manager=session_manager,
        claude_client=claude_client,
        tool_registry=tool_registry,
        memory_injector=memory_injector,
        settings=settings,
    )


async def run_chat_turn(
    deps: TUIDeps,
    user_id: int,
    session_key: str,
    text: str,
    on_event: Callable[[StreamEvent], Awaitable[None]],
) -> None:
    """
    Run one chat turn via MessageProcessingService.
    Calls on_event for each stream event (TextChunk, ToolStatusChunk, etc.).
    """
    from ..bot.chat_service import MessageProcessingDeps, MessageProcessingService

    service = MessageProcessingService(
        MessageProcessingDeps(
            conv_store=deps.conv_store,
            claude_client=deps.claude_client,
            tool_registry=deps.tool_registry,
            memory_injector=deps.memory_injector,
            session_manager=deps.session_manager,
            settings=deps.settings,
        )
    )
    await service.process_text(user_id, text, session_key, on_event)
