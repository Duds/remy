"""
Telegram bot application builder and runner.
Registers all handlers and starts polling or webhook depending on environment.
"""

import logging
import os

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from ..config import settings

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, handlers: dict) -> None:
        self.application = Application.builder().token(settings.telegram_bot_token).build()
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
        app.add_handler(CommandHandler("goals", handlers["goals"]))
        app.add_handler(CommandHandler("delete_conversation", handlers.get("delete_conversation")))
        app.add_handler(CommandHandler("read", handlers.get("read")))
        app.add_handler(CommandHandler("write", handlers.get("write")))
        app.add_handler(CommandHandler("ls", handlers.get("ls")))
        app.add_handler(CommandHandler("find", handlers.get("find")))
        app.add_handler(CommandHandler("set_project", handlers.get("set_project")))
        app.add_handler(CommandHandler("project_status", handlers.get("project_status")))
        app.add_handler(CommandHandler("scan_downloads", handlers.get("scan_downloads")))
        app.add_handler(CommandHandler("organize", handlers.get("organize")))
        app.add_handler(CommandHandler("clean", handlers.get("clean")))
        app.add_handler(CommandHandler("calendar", handlers.get("calendar")))
        app.add_handler(CommandHandler("calendar_today", handlers.get("calendar-today")))
        app.add_handler(CommandHandler("schedule", handlers.get("schedule")))
        app.add_handler(CommandHandler("gmail_unread", handlers.get("gmail-unread")))
        app.add_handler(CommandHandler("gmail_unread_summary", handlers.get("gmail-unread-summary")))
        app.add_handler(CommandHandler("gmail_classify", handlers.get("gmail-classify")))
        app.add_handler(CommandHandler("gdoc", handlers.get("gdoc")))
        app.add_handler(CommandHandler("gdoc_append", handlers.get("gdoc-append")))
        app.add_handler(CommandHandler("contacts", handlers.get("contacts")))
        app.add_handler(CommandHandler("contacts_birthday", handlers.get("contacts-birthday")))
        app.add_handler(CommandHandler("contacts_details", handlers.get("contacts-details")))
        app.add_handler(CommandHandler("contacts_note", handlers.get("contacts-note")))
        app.add_handler(CommandHandler("contacts_prune", handlers.get("contacts-prune")))
        app.add_handler(CommandHandler("search", handlers.get("search")))
        app.add_handler(CommandHandler("research", handlers.get("research")))
        app.add_handler(CommandHandler("save_url", handlers.get("save-url")))
        app.add_handler(CommandHandler("bookmarks", handlers.get("bookmarks")))
        app.add_handler(CommandHandler("grocery_list", handlers.get("grocery-list")))
        app.add_handler(CommandHandler("price_check", handlers.get("price-check")))
        app.add_handler(CommandHandler("board", handlers["board"]))
        app.add_handler(CommandHandler("logs", handlers["logs"]))
        app.add_handler(CommandHandler("schedule_daily", handlers.get("schedule-daily")))
        app.add_handler(CommandHandler("schedule_weekly", handlers.get("schedule-weekly")))
        app.add_handler(CommandHandler("list_automations", handlers.get("list-automations")))
        app.add_handler(CommandHandler("unschedule", handlers.get("unschedule")))
        app.add_handler(CommandHandler("retrospective", handlers.get("retrospective")))
        app.add_handler(CommandHandler("breakdown", handlers.get("breakdown")))
        app.add_handler(CommandHandler("stats", handlers.get("stats")))
        app.add_handler(CommandHandler("goal_status", handlers.get("goal-status")))
        app.add_handler(CommandHandler("gmail_search", handlers.get("gmail-search")))
        app.add_handler(CommandHandler("gmail_read", handlers.get("gmail-read")))
        app.add_handler(CommandHandler("gmail_labels", handlers.get("gmail-labels")))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handlers["message"])
        )
        app.add_handler(
            MessageHandler(filters.VOICE, handlers["voice"])
        )
        app.add_handler(
            MessageHandler(filters.PHOTO, handlers["photo"])
        )

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
        self.application.run_polling(drop_pending_updates=True)
