"""
Tests for the handlers package structure.

Verifies that the refactored handlers package:
1. All submodules import without error
2. Each make_*_handlers() factory returns expected handler names
3. The composed make_handlers() returns all handlers
4. Re-exported utilities are accessible from the package root
"""

import pytest


class TestSubmoduleImports:
    """Verify all handler submodules import without error."""

    def test_import_base(self):
        from remy.bot.handlers import base
        assert hasattr(base, "is_allowed")
        assert hasattr(base, "reject_unauthorized")
        assert hasattr(base, "_build_message_from_turn")
        assert hasattr(base, "_trim_messages_to_budget")
        assert hasattr(base, "MessageRotator")

    def test_import_core(self):
        from remy.bot.handlers import core
        assert hasattr(core, "make_core_handlers")

    def test_import_files(self):
        from remy.bot.handlers import files
        assert hasattr(files, "make_file_handlers")

    def test_import_email(self):
        from remy.bot.handlers import email
        assert hasattr(email, "make_email_handlers")

    def test_import_calendar(self):
        from remy.bot.handlers import calendar
        assert hasattr(calendar, "make_calendar_handlers")

    def test_import_contacts(self):
        from remy.bot.handlers import contacts
        assert hasattr(contacts, "make_contacts_handlers")

    def test_import_docs(self):
        from remy.bot.handlers import docs
        assert hasattr(docs, "make_docs_handlers")

    def test_import_web(self):
        from remy.bot.handlers import web
        assert hasattr(web, "make_web_handlers")

    def test_import_memory(self):
        from remy.bot.handlers import memory
        assert hasattr(memory, "make_memory_handlers")

    def test_import_automations(self):
        from remy.bot.handlers import automations
        assert hasattr(automations, "make_automation_handlers")

    def test_import_admin(self):
        from remy.bot.handlers import admin
        assert hasattr(admin, "make_admin_handlers")

    def test_import_privacy(self):
        from remy.bot.handlers import privacy
        assert hasattr(privacy, "make_privacy_handlers")

    def test_import_chat(self):
        from remy.bot.handlers import chat
        assert hasattr(chat, "make_chat_handlers")


class TestReExportedUtilities:
    """Verify utilities are accessible from package root."""

    def test_build_message_from_turn_exported(self):
        from remy.bot.handlers import _build_message_from_turn
        assert callable(_build_message_from_turn)

    def test_trim_messages_to_budget_exported(self):
        from remy.bot.handlers import _trim_messages_to_budget
        assert callable(_trim_messages_to_budget)

    def test_tool_turn_prefix_exported(self):
        from remy.bot.handlers import _TOOL_TURN_PREFIX
        assert isinstance(_TOOL_TURN_PREFIX, str)


class TestMakeHandlersFactories:
    """Verify each factory returns expected handlers."""

    def test_make_core_handlers(self):
        from remy.bot.handlers.core import make_core_handlers
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        handlers = make_core_handlers(session_manager=mock_session)
        expected = {"start", "help", "cancel", "status", "setmychat", "briefing"}
        assert expected.issubset(set(handlers.keys()))

    def test_make_file_handlers(self):
        from remy.bot.handlers.files import make_file_handlers

        handlers = make_file_handlers()
        expected = {"read", "write", "ls", "find", "set_project", "project_status"}
        assert expected.issubset(set(handlers.keys()))

    def test_make_email_handlers(self):
        from remy.bot.handlers.email import make_email_handlers

        handlers = make_email_handlers()
        expected = {
            "gmail-unread",
            "gmail-unread-summary",
            "gmail-classify",
            "gmail-search",
            "gmail-read",
            "gmail-labels",
        }
        assert expected.issubset(set(handlers.keys()))

    def test_make_calendar_handlers(self):
        from remy.bot.handlers.calendar import make_calendar_handlers

        handlers = make_calendar_handlers()
        expected = {"calendar", "calendar-today", "schedule"}
        assert expected.issubset(set(handlers.keys()))

    def test_make_contacts_handlers(self):
        from remy.bot.handlers.contacts import make_contacts_handlers

        handlers = make_contacts_handlers()
        expected = {
            "contacts",
            "contacts-birthday",
            "contacts-details",
            "contacts-note",
            "contacts-prune",
        }
        assert expected.issubset(set(handlers.keys()))

    def test_make_docs_handlers(self):
        from remy.bot.handlers.docs import make_docs_handlers

        handlers = make_docs_handlers()
        expected = {"gdoc", "gdoc-append"}
        assert expected.issubset(set(handlers.keys()))

    def test_make_web_handlers(self):
        from remy.bot.handlers.web import make_web_handlers

        handlers = make_web_handlers()
        expected = {
            "search",
            "research",
            "save-url",
            "bookmarks",
            "grocery-list",
            "price-check",
        }
        assert expected.issubset(set(handlers.keys()))

    def test_make_memory_handlers(self):
        from remy.bot.handlers.memory import make_memory_handlers
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        mock_conv = MagicMock()
        handlers = make_memory_handlers(
            session_manager=mock_session,
            conv_store=mock_conv,
        )
        expected = {"goals", "plans", "compact", "delete_conversation", "consolidate"}
        assert expected.issubset(set(handlers.keys()))

    def test_make_automation_handlers(self):
        from remy.bot.handlers.automations import make_automation_handlers

        handlers = make_automation_handlers()
        expected = {
            "schedule-daily",
            "schedule-weekly",
            "list-automations",
            "unschedule",
            "breakdown",
            "board",
        }
        assert expected.issubset(set(handlers.keys()))

    def test_make_admin_handlers(self):
        from remy.bot.handlers.admin import make_admin_handlers

        handlers = make_admin_handlers()
        expected = {
            "logs",
            "stats",
            "costs",
            "goal-status",
            "retrospective",
            "jobs",
            "reindex",
            "diagnostics",
        }
        assert expected.issubset(set(handlers.keys()))

    def test_make_privacy_handlers(self):
        from remy.bot.handlers.privacy import make_privacy_handlers
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        mock_conv = MagicMock()
        handlers = make_privacy_handlers(
            session_manager=mock_session,
            conv_store=mock_conv,
        )
        expected = {"privacy-audit"}
        assert expected.issubset(set(handlers.keys()))

    def test_make_chat_handlers(self):
        from remy.bot.handlers.chat import make_chat_handlers
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        mock_router = MagicMock()
        mock_conv = MagicMock()
        handlers = make_chat_handlers(
            session_manager=mock_session,
            router=mock_router,
            conv_store=mock_conv,
        )
        assert "message" in handlers


class TestComposedMakeHandlers:
    """Verify the main make_handlers() composes all handlers correctly."""

    def test_make_handlers_returns_all_handlers(self):
        from remy.bot.handlers import make_handlers

        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
        )
        assert len(handlers) >= 50

    def test_make_handlers_includes_core_commands(self):
        from remy.bot.handlers import make_handlers

        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
        )
        core_commands = {"start", "help", "cancel", "status"}
        assert core_commands.issubset(set(handlers.keys()))

    def test_make_handlers_includes_google_commands(self):
        from remy.bot.handlers import make_handlers

        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
        )
        google_commands = {
            "gmail-unread",
            "calendar",
            "contacts",
            "gdoc",
        }
        assert google_commands.issubset(set(handlers.keys()))

    def test_make_handlers_includes_file_commands(self):
        from remy.bot.handlers import make_handlers

        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
        )
        file_commands = {"read", "write", "ls", "find"}
        assert file_commands.issubset(set(handlers.keys()))

    def test_make_handlers_includes_message_handler(self):
        from remy.bot.handlers import make_handlers

        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
        )
        assert "message" in handlers

    def test_all_handlers_are_callable(self):
        from remy.bot.handlers import make_handlers

        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
        )
        for name, handler in handlers.items():
            assert callable(handler), f"Handler '{name}' is not callable"
