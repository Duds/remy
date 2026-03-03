"""
Web and shopping handlers.

Contains handlers for web search, research, bookmarks, grocery list, and price checking.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized
from ...config import settings
from ...utils.telegram_formatting import format_telegram_message

if TYPE_CHECKING:
    from ...memory.facts import FactStore

logger = logging.getLogger(__name__)


def make_web_handlers(
    *,
    claude_client=None,
    fact_store: "FactStore | None" = None,
):
    """
    Factory that returns web and shopping handlers.
    
    Returns a dict of command_name -> handler_function.
    """

    async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/search <query> — DuckDuckGo web search, returns top results."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /search <query>")
            return
        from ...web.search import web_search, format_results
        query = " ".join(context.args)
        await update.message.reply_text(f"🔍 Searching for _{query}_…", parse_mode="Markdown")
        results = await web_search(query, max_results=5)
        if not results:
            await update.message.reply_text(
                "❌ Search unavailable right now. "
                "Make sure `duckduckgo-search` is installed, or try again later."
            )
            return
        msg = f"🔍 *Results for \"{query}\":*\n\n" + format_results(results)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(format_telegram_message(msg), parse_mode="MarkdownV2")

    async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/research <topic> — web search + Claude synthesis of findings."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /research <topic>")
            return
        if claude_client is None:
            await update.message.reply_text("❌ Claude not available for research synthesis.")
            return
        from ...web.search import web_search
        from ..working_message import WorkingMessage

        topic = " ".join(context.args)
        thread_id: int | None = getattr(update.message, "message_thread_id", None)

        wm = WorkingMessage(context.bot, update.message.chat_id, thread_id)
        await wm.start()

        try:
            results = await web_search(topic, max_results=5)
            if not results:
                await wm.stop()
                await update.message.reply_text(
                    "❌ Web search unavailable. Install `duckduckgo-search` or try again later."
                )
                return

            snippets = "\n\n".join(
                f"Source {i}: {r.get('title','')}\nURL: {r.get('href','')}\n{r.get('body','')}"
                for i, r in enumerate(results, 1)
            )

            synthesis = await claude_client.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Research topic: {topic}\n\n"
                        f"Web search results:\n{snippets}\n\n"
                        "Synthesise the key findings into a clear, useful summary. "
                        "Cite source numbers. Be factual and concise."
                    ),
                }],
                system="You are a research assistant. Synthesise web search results accurately.",
                max_tokens=1024,
            )

            await wm.stop()
            msg = f"📚 *Research: {topic}*\n\n{synthesis}"
            if len(msg) > 4000:
                msg = msg[:4000] + "…"
            await update.message.reply_text(format_telegram_message(msg), parse_mode="MarkdownV2")
        except Exception as e:
            await wm.stop()
            await update.message.reply_text(f"❌ Could not synthesise results: {e}")

    async def save_url_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/save-url <url> [note] — save a bookmark."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /save-url <url> [optional note]")
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        url = context.args[0]
        note = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        content = f"{url} — {note}" if note else url
        await fact_store.add(update.effective_user.id, "bookmark", content)
        await update.message.reply_text(
            f"🔖 Bookmark saved: {content}", parse_mode="Markdown"
        )

    async def bookmarks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/bookmarks [filter] — list saved bookmarks, optionally filtered."""
        if await reject_unauthorized(update):
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        items = await fact_store.get_by_category(update.effective_user.id, "bookmark")
        if not items:
            await update.message.reply_text("🔖 No bookmarks saved yet. Use /save-url <url> to add one.")
            return
        filt = " ".join(context.args).lower() if context.args else ""
        if filt:
            items = [b for b in items if filt in b["content"].lower()]
        if not items:
            await update.message.reply_text(f"🔖 No bookmarks matching '{filt}'.")
            return
        lines = [f"🔖 *Bookmarks{' (filtered)' if filt else ''} — {len(items)} item(s):*\n"]
        for i, b in enumerate(items[:20], 1):
            lines.append(f"{i}. {b['content']}")
        if len(items) > 20:
            lines.append(f"…and {len(items) - 20} more")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def grocery_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /grocery-list              — show current list
        /grocery-list add <items>  — add items (comma-separated or space-separated)
        /grocery-list done <item>  — remove item by name
        /grocery-list clear        — clear the whole list
        """
        if await reject_unauthorized(update):
            return

        grocery_file = settings.grocery_list_file

        def _read_items() -> list[str]:
            try:
                with open(grocery_file, encoding="utf-8") as f:
                    return [line.strip() for line in f if line.strip()]
            except FileNotFoundError:
                return []

        def _write_items(items: list[str]) -> None:
            Path(grocery_file).parent.mkdir(parents=True, exist_ok=True)
            with open(grocery_file, "w", encoding="utf-8") as f:
                f.write("\n".join(items) + ("\n" if items else ""))

        sub = context.args[0].lower() if context.args else ""

        if sub == "add":
            raw = " ".join(context.args[1:])
            if not raw:
                await update.message.reply_text("Usage: /grocery-list add <items>")
                return
            new_items = [i.strip() for i in raw.split(",") if i.strip()] if "," in raw else [raw.strip()]
            current = await asyncio.to_thread(_read_items)
            await asyncio.to_thread(_write_items, current + new_items)
            added = ", ".join(new_items)
            await update.message.reply_text(f"✅ Added: {added}")

        elif sub == "done":
            item_name = " ".join(context.args[1:]).strip().lower()
            if not item_name:
                await update.message.reply_text("Usage: /grocery-list done <item>")
                return
            current = await asyncio.to_thread(_read_items)
            updated = [i for i in current if i.lower() != item_name]
            if len(updated) == len(current):
                await update.message.reply_text(f"❌ '{item_name}' not found in the list.")
                return
            await asyncio.to_thread(_write_items, updated)
            await update.message.reply_text(f"✅ Removed: {item_name}")

        elif sub == "clear":
            await asyncio.to_thread(_write_items, [])
            await update.message.reply_text("✅ Grocery list cleared.")

        else:
            items = await asyncio.to_thread(_read_items)
            if not items:
                await update.message.reply_text(
                    "🛒 Grocery list is empty.\n"
                    "Use `/grocery-list add milk, eggs, bread` to add items.",
                    parse_mode="Markdown",
                )
                return
            lines = [f"🛒 *Grocery list — {len(items)} item(s):*\n"]
            lines += [f"• {item}" for item in items]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def price_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/price-check <item> — search for current prices and synthesise with Claude."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /price-check <item>")
            return
        from ...web.search import web_search
        item = " ".join(context.args)
        await update.message.reply_text(f"🏷 Checking prices for _{item}_…", parse_mode="Markdown")
        results = await web_search(f"{item} price Australia buy", max_results=5)
        if not results:
            await update.message.reply_text("❌ Web search unavailable right now.")
            return
        if claude_client is None:
            from ...web.search import format_results
            await update.message.reply_text(
                f"🏷 *Price results for {item}:*\n\n" + format_results(results),
                parse_mode="Markdown",
            )
            return
        snippets = "\n\n".join(
            f"Source {i}: {r.get('title','')}\n{r.get('body','')}"
            for i, r in enumerate(results, 1)
        )
        try:
            analysis = await claude_client.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Item: {item}\n\nSearch results:\n{snippets}\n\n"
                        "Extract and compare the prices mentioned. "
                        "List the best options with their prices and sources. "
                        "Be concise and factual."
                    ),
                }],
                system="You are a shopping assistant. Extract and compare prices from search results.",
                max_tokens=512,
            )
            msg = f"🏷 *Price check: {item}*\n\n{analysis}"
            if len(msg) > 4000:
                msg = msg[:4000] + "…"
            await update.message.reply_text(format_telegram_message(msg), parse_mode="MarkdownV2")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not analyse prices: {e}")

    return {
        "search": search_command,
        "research": research_command,
        "save-url": save_url_command,
        "bookmarks": bookmarks_command,
        "grocery-list": grocery_list_command,
        "price-check": price_check_command,
    }
