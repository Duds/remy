"""
Tests for Phase 4: web search, bookmarks, grocery list.
Search results are mocked — no network required.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── web/search helpers ────────────────────────────────────────────────────────


def test_format_results_empty():
    from remy.web.search import format_results

    assert "_No results found._" in format_results([])


def test_format_results_basic():
    from remy.web.search import format_results

    results = [
        {"title": "Python Docs", "href": "https://python.org", "body": "The Python programming language."},
    ]
    out = format_results(results)
    assert "Python Docs" in out
    assert "python.org" in out


def test_format_results_truncates_body():
    from remy.web.search import format_results

    long_body = "x" * 500
    results = [{"title": "T", "href": "https://example.com", "body": long_body}]
    out = format_results(results, max_body=100)
    assert len(out) < 600
    assert "…" in out


# ── web_search mocking ────────────────────────────────────────────────────────


def test_web_search_returns_results():
    fake = [{"title": "Python", "href": "https://python.org", "body": "Python lang."}]
    with patch("remy.web.search.asyncio.to_thread", new=AsyncMock(return_value=fake)):
        from remy.web.search import web_search
        results = asyncio.run(web_search("python"))
    assert results == fake


def test_web_search_error_returns_empty():
    """If DuckDuckGo raises an error, web_search returns [] gracefully."""
    # Patch at the ddgs package level so the import inside _sync() gets the mock
    with patch.dict("sys.modules", {"ddgs": MagicMock()}):
        import sys
        mock_ddgs_module = sys.modules["ddgs"]
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.__enter__.return_value.text.side_effect = RuntimeError("rate limited")
        mock_ddgs_module.DDGS.return_value = mock_ddgs_instance
        
        from remy.web.search import web_search
        results = asyncio.run(web_search("test"))
    assert results == []


# ── handler smoke tests ───────────────────────────────────────────────────────


class DummyMessage:
    def __init__(self):
        self.last_text = None

    async def reply_text(self, text, parse_mode=None):
        self.last_text = text


def make_update(user_id=12345):
    class User:
        id = user_id
        username = None
        first_name = None
        last_name = None

    class Update:
        effective_user = User()
        message = DummyMessage()
        effective_chat = User()

    return Update()


def make_context(args=None):
    class Context:
        def __init__(self, a):
            self.args = a or []

    return Context(args)


def test_search_no_args():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(session_manager=None, router=None, conv_store=None)
    update = make_update()
    asyncio.run(handlers["search"](update, make_context()))
    assert "Usage:" in update.message.last_text


def test_research_no_args():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(session_manager=None, router=None, conv_store=None)
    update = make_update()
    asyncio.run(handlers["research"](update, make_context()))
    assert "Usage:" in update.message.last_text


def test_search_with_results():
    from remy.bot.handlers import make_handlers

    fake_results = [
        {"title": "Python", "href": "https://python.org", "body": "The Python language."}
    ]
    with patch("remy.web.search.asyncio.to_thread", new=AsyncMock(return_value=fake_results)):
        handlers = make_handlers(session_manager=None, router=None, conv_store=None)
        update = make_update()
        asyncio.run(handlers["search"](update, make_context(["python", "programming"])))
    assert "Python" in update.message.last_text


def test_save_url_no_fact_store():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(session_manager=None, router=None, conv_store=None, fact_store=None)
    update = make_update()
    asyncio.run(handlers["save-url"](update, make_context(["https://python.org"])))
    assert "not available" in update.message.last_text.lower()


def test_save_url_with_fact_store():
    from remy.bot.handlers import make_handlers

    mock_fs = MagicMock()
    mock_fs.add = AsyncMock()
    mock_fs.get_by_category = AsyncMock(return_value=[])
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, fact_store=mock_fs
    )
    update = make_update()
    asyncio.run(handlers["save-url"](update, make_context(["https://python.org", "Python", "docs"])))
    mock_fs.add.assert_called_once()
    assert "Bookmark saved" in update.message.last_text


def test_bookmarks_empty():
    from remy.bot.handlers import make_handlers

    mock_fs = MagicMock()
    mock_fs.get_by_category = AsyncMock(return_value=[])
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, fact_store=mock_fs
    )
    update = make_update()
    asyncio.run(handlers["bookmarks"](update, make_context()))
    assert "No bookmarks" in update.message.last_text


def test_bookmarks_list():
    from remy.bot.handlers import make_handlers

    mock_fs = MagicMock()
    mock_fs.get_by_category = AsyncMock(return_value=[
        {"content": "https://python.org — Python docs"},
        {"content": "https://realpython.com"},
    ])
    handlers = make_handlers(
        session_manager=None, router=None, conv_store=None, fact_store=mock_fs
    )
    update = make_update()
    asyncio.run(handlers["bookmarks"](update, make_context()))
    assert "python.org" in update.message.last_text
    assert "2 item" in update.message.last_text


def test_grocery_list_show_empty(tmp_path):
    from remy.bot.handlers import make_handlers

    with patch("remy.bot.handlers.web.settings") as mock_settings, \
         patch("remy.bot.handlers.base.settings") as mock_base_settings:
        mock_settings.telegram_allowed_users = [12345]
        mock_settings.grocery_list_file = str(tmp_path / "grocery.txt")
        mock_base_settings.telegram_allowed_users = [12345]
        handlers = make_handlers(session_manager=None, router=None, conv_store=None)
        update = make_update()
        asyncio.run(handlers["grocery-list"](update, make_context()))
    assert "empty" in update.message.last_text.lower()


def test_grocery_list_add_and_show(tmp_path):
    from remy.bot.handlers import make_handlers

    grocery_file = str(tmp_path / "grocery.txt")
    with patch("remy.bot.handlers.web.settings") as mock_settings, \
         patch("remy.bot.handlers.base.settings") as mock_base_settings:
        mock_settings.telegram_allowed_users = [12345]
        mock_settings.grocery_list_file = grocery_file
        mock_base_settings.telegram_allowed_users = [12345]
        handlers = make_handlers(session_manager=None, router=None, conv_store=None)
        update = make_update()

        # Add items
        asyncio.run(handlers["grocery-list"](update, make_context(["add", "milk,", "eggs"])))
        assert "Added" in update.message.last_text

        # Show list
        asyncio.run(handlers["grocery-list"](update, make_context()))
    assert "milk" in update.message.last_text


def test_grocery_list_done(tmp_path):
    from remy.bot.handlers import make_handlers

    grocery_file = str(tmp_path / "grocery.txt")
    Path(grocery_file).write_text("milk\neggs\nbread\n")

    with patch("remy.bot.handlers.web.settings") as mock_settings, \
         patch("remy.bot.handlers.base.settings") as mock_base_settings:
        mock_settings.telegram_allowed_users = [12345]
        mock_settings.grocery_list_file = grocery_file
        mock_base_settings.telegram_allowed_users = [12345]
        handlers = make_handlers(session_manager=None, router=None, conv_store=None)
        update = make_update()
        asyncio.run(handlers["grocery-list"](update, make_context(["done", "eggs"])))

    assert "Removed" in update.message.last_text
    remaining = Path(grocery_file).read_text()
    assert "eggs" not in remaining
    assert "milk" in remaining


def test_grocery_list_clear(tmp_path):
    from remy.bot.handlers import make_handlers

    grocery_file = str(tmp_path / "grocery.txt")
    Path(grocery_file).write_text("milk\neggs\n")

    with patch("remy.bot.handlers.web.settings") as mock_settings, \
         patch("remy.bot.handlers.base.settings") as mock_base_settings:
        mock_settings.telegram_allowed_users = [12345]
        mock_settings.grocery_list_file = grocery_file
        mock_base_settings.telegram_allowed_users = [12345]
        handlers = make_handlers(session_manager=None, router=None, conv_store=None)
        update = make_update()
        asyncio.run(handlers["grocery-list"](update, make_context(["clear"])))

    assert "cleared" in update.message.last_text.lower()
    assert Path(grocery_file).read_text().strip() == ""


def test_price_check_no_args():
    from remy.bot.handlers import make_handlers

    handlers = make_handlers(session_manager=None, router=None, conv_store=None)
    update = make_update()
    asyncio.run(handlers["price-check"](update, make_context()))
    assert "Usage:" in update.message.last_text
