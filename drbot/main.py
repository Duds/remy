"""
drbot entry point.
Initialises all components and starts the Telegram bot.
"""

import asyncio
import logging
import os
import signal

from .agents.orchestrator import BoardOrchestrator
from .ai.claude_client import ClaudeClient
from .ai.ollama_client import OllamaClient
from .ai.router import ModelRouter
from .ai.tool_registry import ToolRegistry
from .bot.handlers import make_handlers
from .bot.session import SessionManager
from .bot.telegram_bot import TelegramBot
from .config import settings
from .health import run_health_server, set_ready
from .logging_config import setup_logging
from .memory.automations import AutomationStore
from .memory.conversations import ConversationStore
from .memory.database import DatabaseManager
from .memory.embeddings import EmbeddingStore
from .memory.facts import FactExtractor, FactStore
from .memory.fts import FTSSearch
from .memory.goals import GoalExtractor, GoalStore
from .memory.injector import MemoryInjector
from .analytics.analyzer import ConversationAnalyzer
from .scheduler.proactive import ProactiveScheduler
from .voice.transcriber import VoiceTranscriber

logger = logging.getLogger(__name__)


async def health_monitor(claude_client: ClaudeClient, bot) -> None:
    """
    Periodic health check every 5 minutes.
    Alerts the first allowed user if Claude becomes unavailable.
    """
    consecutive_failures = 0
    while True:
        await asyncio.sleep(300)  # 5 minutes
        available = await claude_client.ping()
        if not available:
            consecutive_failures += 1
            logger.warning(
                "Claude health check failed (consecutive: %d)", consecutive_failures
            )
            if consecutive_failures >= 2 and settings.telegram_allowed_users:
                try:
                    await bot.send_message(
                        chat_id=settings.telegram_allowed_users[0],
                        text="drbot: Claude API is unavailable. Falling back to Ollama.",
                    )
                except Exception as e:
                    logger.error("Could not send health alert: %s", e)
        else:
            consecutive_failures = 0


def main() -> None:
    # Ensure data directories exist
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.sessions_dir, exist_ok=True)
    os.makedirs(settings.logs_dir, exist_ok=True)

    # Configure logging
    setup_logging(settings.log_level, settings.logs_dir, settings.azure_environment)

    logger.info(
        "Starting drbot (env=%s, data_dir=%s)",
        "azure" if settings.azure_environment else "local",
        settings.data_dir,
    )

    # Initialise AI components
    claude_client = ClaudeClient()
    ollama_client = OllamaClient()
    router = ModelRouter(claude_client, ollama_client)
    session_manager = SessionManager()
    conv_store = ConversationStore(settings.sessions_dir)

    # Board of Directors orchestrator (Phase 5)
    board_orchestrator = BoardOrchestrator(claude_client)

    # Tool registry — enables native Anthropic tool use (function calling)
    # Wired after memory components are initialised below
    # (fact_store and goal_store are set up in the next block)

    # Initialise memory components (database init is async; done in post_init)
    db = DatabaseManager()
    embeddings = EmbeddingStore(db)
    fact_store = FactStore(db, embeddings)
    fact_extractor = FactExtractor(claude_client)
    goal_store = GoalStore(db, embeddings)
    goal_extractor = GoalExtractor(claude_client)
    fts = FTSSearch(db)
    memory_injector = MemoryInjector(db, embeddings, fact_store, goal_store, fts)
    automation_store = AutomationStore(db)
    conv_analyzer = ConversationAnalyzer(conv_store, db)

    # Initialise voice transcriber (lazy — Whisper model loads on first voice message)
    voice_transcriber = VoiceTranscriber()

    # Google Workspace clients (Phase 3).
    # Auth: ADC (gcloud auth application-default login) takes priority over token file.
    # Setup: see scripts/setup_google_auth.py or GCLOUD_ADC_COMMAND in drbot/google/auth.py.
    google_calendar = None
    google_gmail = None
    google_docs = None
    google_contacts = None
    try:
        from .google.auth import is_configured, GCLOUD_ADC_COMMAND
        token_file = settings.google_token_file
        if is_configured(token_file):
            from .google.calendar import CalendarClient
            from .google.gmail import GmailClient
            from .google.docs import DocsClient
            from .google.contacts import ContactsClient
            google_calendar = CalendarClient(token_file, timezone=settings.scheduler_timezone)
            google_gmail = GmailClient(token_file)
            google_docs = DocsClient(token_file)
            google_contacts = ContactsClient(token_file)
            logger.info("Google Workspace integration enabled (Calendar, Gmail, Docs, Contacts)")
        else:
            logger.info(
                "Google Workspace not configured. Authenticate with:\n  %s\n"
                "or: python scripts/setup_google_auth.py",
                GCLOUD_ADC_COMMAND,
            )
    except ImportError:
        logger.info("Google API libraries not installed — Workspace integration disabled")
    except Exception as e:
        logger.warning("Google Workspace init failed: %s", e)

    # Mutable container for late-binding the proactive scheduler.
    # Must be defined before ToolRegistry so it can be passed in as scheduler_ref.
    # The /briefing proxy and tool executors read from this dict at call time.
    _late: dict = {"proactive_scheduler": None}

    # Tool registry — all tools wired in for natural language invocation.
    # Google Workspace clients may be None if not configured; tools degrade gracefully.
    tool_registry = ToolRegistry(
        logs_dir=settings.logs_dir,
        goal_store=goal_store,
        fact_store=fact_store,
        board_orchestrator=board_orchestrator,
        claude_client=claude_client,
        ollama_base_url=settings.ollama_base_url,
        model_complex=settings.model_complex,
        # Google Workspace (None if not configured)
        calendar_client=google_calendar,
        gmail_client=google_gmail,
        contacts_client=google_contacts,
        docs_client=google_docs,
        # Phase 5: automations
        automation_store=automation_store,
        scheduler_ref=_late,  # populated after post_init; tools read it at call time
        # Files / grocery
        grocery_list_file=settings.grocery_list_file,
        # Phase 6: analytics
        conversation_analyzer=conv_analyzer,
    )

    async def _briefing_proxy(update, context):
        """Late-bound /briefing handler — delegates to scheduler once available."""
        sched = _late["proactive_scheduler"]
        if sched is None:
            await update.message.reply_text("Proactive scheduler not running.")
            return
        await update.message.reply_text("Sending briefing…")
        await sched.send_morning_briefing_now()

    # Build all handlers; /briefing is overridden with the late-bound proxy below
    handlers = make_handlers(
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
        proactive_scheduler=None,  # /goals works immediately; /briefing via proxy
        board_orchestrator=board_orchestrator,
        db=db,
        tool_registry=tool_registry,  # Native Anthropic tool use
        google_calendar=google_calendar,
        google_gmail=google_gmail,
        google_docs=google_docs,
        google_contacts=google_contacts,
        automation_store=automation_store,
        scheduler_ref=_late,  # mutable container; scheduler set after post_init
        conversation_analyzer=conv_analyzer,
    )
    handlers["briefing"] = _briefing_proxy

    # Build bot (registers all handlers)
    bot = TelegramBot(handlers=handlers)

    # Keep reference for SIGTERM shutdown
    _proactive_ref: list[ProactiveScheduler] = []
    _health_task: list[asyncio.Task] = []

    def _handle_sigterm(signum, frame):
        logger.info("SIGTERM received — shutting down")
        if _proactive_ref:
            _proactive_ref[0].stop()
        for task in _health_task:
            task.cancel()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _on_post_init(app):
        # Start health HTTP server immediately so the container is reachable
        # during the /ready 503 "starting" phase
        health_port = int(os.environ.get("HEALTH_PORT", "8080"))
        task = asyncio.create_task(run_health_server(port=health_port))
        _health_task.append(task)

        # Initialise database schema
        await db.init()
        logger.info("Database initialised")

        # Wire proactive scheduler (requires live bot reference from PTB)
        sched = ProactiveScheduler(
            app.bot, goal_store, fact_store, google_calendar, google_contacts,
            automation_store=automation_store,
            claude_client=claude_client,
            conversation_analyzer=conv_analyzer,
        )
        _late["proactive_scheduler"] = sched
        _proactive_ref.append(sched)
        sched.start()

        # Load user-defined automations from DB into the live scheduler
        await sched.load_user_automations()

        asyncio.create_task(health_monitor(claude_client, app.bot))

        # Signal readiness — /ready now returns 200
        set_ready()

    bot.application.post_init = _on_post_init

    logger.info("drbot ready")
    bot.run()


if __name__ == "__main__":
    main()
