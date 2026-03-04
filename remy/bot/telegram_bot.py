"""
Telegram bot application builder and runner.
Registers all handlers and starts polling or webhook depending on environment.

Connection resilience: Configures generous timeouts to handle transient
Telegram API disconnections gracefully (Bug 6 mitigation).
"""

import logging
import os

import telegram.error
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    MessageReactionHandler,
    filters,
)

from ..config import settings

logger = logging.getLogger(__name__)


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch-all error handler registered with PTB Application.

    Transient errors (network, timeout, forbidden) are logged at WARNING.
    Unexpected errors are logged at ERROR with update context and trigger
    a Telegram alert to the first allowed user.
    """
    err = context.error

    # Record error in Prometheus metrics if available
    try:
        from ..analytics.metrics import record_error

        if isinstance(err, telegram.error.NetworkError):
            record_error("telegram_network")
        elif isinstance(err, telegram.error.TimedOut):
            record_error("telegram_timeout")
        else:
            record_error("telegram_other")
    except ImportError:
        pass

    if isinstance(
        err,
        (
            telegram.error.NetworkError,
            telegram.error.TimedOut,
            telegram.error.Forbidden,
        ),
    ):
        logger.warning("Telegram transient error: %s", err)
        return

    user_id = None
    update_type = type(update).__name__ if update else "unknown"
    if hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id
    logger.error(
        "Unhandled Telegram exception (update_type=%s, user=%s): %s",
        update_type,
        user_id,
        err,
        exc_info=context.error,
    )
    if settings.telegram_allowed_users:
        try:
            await context.bot.send_message(
                chat_id=settings.telegram_allowed_users[0],
                text=f"\u26a0\ufe0f *Remy error:* `{type(err).__name__}: {err}`",
                parse_mode="Markdown",
            )
        except Exception as notify_err:
            logger.debug("Failed to send error notification to admin: %s", notify_err)


class TelegramBot:
    def __init__(self, handlers: dict) -> None:
        # Build application with resilient timeout configuration
        timeout = settings.telegram_timeout
        self.application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .http_version("1.1")
            .connect_timeout(timeout)
            .read_timeout(timeout)
            .write_timeout(timeout)
            .pool_timeout(timeout)
            .get_updates_connect_timeout(timeout)
            .get_updates_read_timeout(timeout)
            .get_updates_write_timeout(timeout)
            .get_updates_pool_timeout(timeout)
            .build()
        )
        self._register_handlers(handlers)

    def _register_handlers(self, handlers: dict) -> None:
        app = self.application
        app.add_handler(CommandHandler("start", handlers["start"]))
        app.add_handler(CommandHandler("help", handlers["help"]))
        app.add_handler(CommandHandler("cancel", handlers["cancel"]))
        app.add_handler(CommandHandler("status", handlers["status"]))
        app.add_handler(CommandHandler("compact", handlers["compact"]))
        app.add_handler(CommandHandler("setmychat", handlers["setmychat"]))
        app.add_handler(CommandHandler("briefing", handlers["briefing"]))
        app.add_handler(CommandHandler("relay", handlers["relay"]))
        app.add_handler(CommandHandler("goals", handlers["goals"]))
        if (h := handlers.get("delete_conversation")) is not None:
            app.add_handler(CommandHandler("delete_conversation", h))
        if (h := handlers.get("read")) is not None:
            app.add_handler(CommandHandler("read", h))
        if (h := handlers.get("write")) is not None:
            app.add_handler(CommandHandler("write", h))
        if (h := handlers.get("ls")) is not None:
            app.add_handler(CommandHandler("ls", h))
        if (h := handlers.get("find")) is not None:
            app.add_handler(CommandHandler("find", h))
        if (h := handlers.get("set_project")) is not None:
            app.add_handler(CommandHandler("set_project", h))
        if (h := handlers.get("project_status")) is not None:
            app.add_handler(CommandHandler("project_status", h))
        if (h := handlers.get("scan_downloads")) is not None:
            app.add_handler(CommandHandler("scan_downloads", h))
        if (h := handlers.get("organize")) is not None:
            app.add_handler(CommandHandler("organize", h))
        if (h := handlers.get("clean")) is not None:
            app.add_handler(CommandHandler("clean", h))
        if (h := handlers.get("calendar")) is not None:
            app.add_handler(CommandHandler("calendar", h))
        if (h := handlers.get("calendar-today")) is not None:
            app.add_handler(CommandHandler("calendar_today", h))
        if (h := handlers.get("schedule")) is not None:
            app.add_handler(CommandHandler("schedule", h))
        if (h := handlers.get("gmail-unread")) is not None:
            app.add_handler(CommandHandler("gmail_unread", h))
        if (h := handlers.get("gmail-unread-summary")) is not None:
            app.add_handler(CommandHandler("gmail_unread_summary", h))
        if (h := handlers.get("gmail-classify")) is not None:
            app.add_handler(CommandHandler("gmail_classify", h))
        if (h := handlers.get("gdoc")) is not None:
            app.add_handler(CommandHandler("gdoc", h))
        if (h := handlers.get("gdoc-append")) is not None:
            app.add_handler(CommandHandler("gdoc_append", h))
        if (h := handlers.get("contacts")) is not None:
            app.add_handler(CommandHandler("contacts", h))
        if (h := handlers.get("contacts-birthday")) is not None:
            app.add_handler(CommandHandler("contacts_birthday", h))
        if (h := handlers.get("contacts-details")) is not None:
            app.add_handler(CommandHandler("contacts_details", h))
        if (h := handlers.get("contacts-note")) is not None:
            app.add_handler(CommandHandler("contacts_note", h))
        if (h := handlers.get("contacts-prune")) is not None:
            app.add_handler(CommandHandler("contacts_prune", h))
        if (h := handlers.get("search")) is not None:
            app.add_handler(CommandHandler("search", h))
        if (h := handlers.get("research")) is not None:
            app.add_handler(CommandHandler("research", h))
        if (h := handlers.get("save-url")) is not None:
            app.add_handler(CommandHandler("save_url", h))
        if (h := handlers.get("bookmarks")) is not None:
            app.add_handler(CommandHandler("bookmarks", h))
        if (h := handlers.get("grocery-list")) is not None:
            app.add_handler(CommandHandler("grocery_list", h))
        if (h := handlers.get("price-check")) is not None:
            app.add_handler(CommandHandler("price_check", h))
        app.add_handler(CommandHandler("board", handlers["board"]))
        app.add_handler(CommandHandler("logs", handlers["logs"]))
        if (h := handlers.get("schedule-daily")) is not None:
            app.add_handler(CommandHandler("schedule_daily", h))
        if (h := handlers.get("schedule-weekly")) is not None:
            app.add_handler(CommandHandler("schedule_weekly", h))
        if (h := handlers.get("list-automations")) is not None:
            app.add_handler(CommandHandler("list_automations", h))
        if (h := handlers.get("unschedule")) is not None:
            app.add_handler(CommandHandler("unschedule", h))
        if (h := handlers.get("retrospective")) is not None:
            app.add_handler(CommandHandler("retrospective", h))
        if (h := handlers.get("breakdown")) is not None:
            app.add_handler(CommandHandler("breakdown", h))
        if (h := handlers.get("stats")) is not None:
            app.add_handler(CommandHandler("stats", h))
        if (h := handlers.get("costs")) is not None:
            app.add_handler(CommandHandler("costs", h))
        if (h := handlers.get("goal-status")) is not None:
            app.add_handler(CommandHandler("goal_status", h))
        if (h := handlers.get("gmail-search")) is not None:
            app.add_handler(CommandHandler("gmail_search", h))
        if (h := handlers.get("gmail-read")) is not None:
            app.add_handler(CommandHandler("gmail_read", h))
        if (h := handlers.get("gmail-labels")) is not None:
            app.add_handler(CommandHandler("gmail_labels", h))
        if (h := handlers.get("gmail-create-label")) is not None:
            app.add_handler(CommandHandler("gmail_create_label", h))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handlers["message"])
        )
        app.add_handler(MessageHandler(filters.VOICE, handlers["voice"]))
        app.add_handler(MessageHandler(filters.PHOTO, handlers["photo"]))
        app.add_handler(MessageHandler(filters.Document.ALL, handlers["document"]))
        app.add_handler(MessageReactionHandler(handlers["reaction"]))
        if handlers.get("callback"):
            app.add_handler(CallbackQueryHandler(handlers["callback"]))
        app.add_error_handler(_error_handler)

    def run(self) -> None:
        """Start the bot (blocking). Use run_polling locally, webhook in Azure."""
        if settings.azure_environment:
            webhook_url = os.environ.get("WEBHOOK_URL")
            if webhook_url:
                logger.info("Starting bot with webhook: %s", webhook_url)
                self.application.run_webhook(
                    listen="0.0.0.0",
                    port=int(os.environ.get("PORT", 8443)),
                    webhook_url=webhook_url,
                )
                return
        logger.info("Starting bot with polling")
        from telegram import Update

        self.application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
