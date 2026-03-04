"""
Web and shopping handlers.

Contains handlers for web search, research, bookmarks, grocery list, and price checking.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import Update, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from .base import reject_unauthorized
from .callbacks import make_run_again_keyboard
from ...ai.tools.automations import grocery_list_impl
from ...config import settings
from ...utils.telegram_formatting import format_telegram_message

if TYPE_CHECKING:
    from ...memory.facts import FactStore
    from ...memory.knowledge import KnowledgeStore

logger = logging.getLogger(__name__)


async def run_research_flow(
    *,
    bot,
    chat_id: int,
    user_id: int,
    topic: str,
    claude_client,
    thread_id: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """
    Run web search + Claude synthesis and send the result to the chat.
    Used by /research command and by the Run again callback.
    """
    from ...web.search import web_search
    from ..working_message import WorkingMessage

    wm = WorkingMessage(bot, chat_id, thread_id)
    await wm.start()

    async def _upload_action_heartbeat() -> None:
        try:
            while True:
                try:
                    await bot.send_chat_action(
                        chat_id,
                        ChatAction.UPLOAD_DOCUMENT,
                        message_thread_id=thread_id,
                    )
                except Exception as exc:
                    logger.debug("Research chat action heartbeat failed: %s", exc)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(_upload_action_heartbeat())
    try:
        results = await web_search(topic, max_results=5)
        if not results:
            await wm.stop()
            await bot.send_message(
                chat_id,
                "❌ Web search unavailable. Install `duckduckgo-search` or try again later.",
                message_thread_id=thread_id,
            )
            return

        snippets = "\n\n".join(
            f"Source {i}: {r.get('title', '')}\nURL: {r.get('href', '')}\n{r.get('body', '')}"
            for i, r in enumerate(results, 1)
        )

        synthesis = await claude_client.complete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Research topic: {topic}\n\n"
                        f"Web search results:\n{snippets}\n\n"
                        "Synthesise the key findings into a clear, useful summary. "
                        "Cite source numbers. Be factual and concise."
                    ),
                }
            ],
            system="You are a research assistant. Synthesise web search results accurately.",
            max_tokens=1024,
        )

        await wm.stop()
        msg = f"📚 *Research: {topic}*\n\n{synthesis}"
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        send_kwargs = {"parse_mode": "MarkdownV2"}
        if thread_id is not None:
            send_kwargs["message_thread_id"] = thread_id
        if reply_markup is not None:
            send_kwargs["reply_markup"] = reply_markup
        await bot.send_message(
            chat_id,
            format_telegram_message(msg),
            **send_kwargs,
        )
    except Exception as exc:
        await wm.stop()
        await bot.send_message(
            chat_id,
            f"❌ Could not synthesise results: {exc}",
            message_thread_id=thread_id,
        )
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


def make_web_handlers(
    *,
    claude_client=None,
    fact_store: "FactStore | None" = None,
    knowledge_store: "KnowledgeStore | None" = None,
):
    """
    Factory that returns web and shopping handlers.

    Returns a dict of command_name -> handler_function.
    """

    async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/search <query> — DuckDuckGo web search, returns top results."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /search <query>")
            return
        from ...web.search import web_search, format_results

        query = " ".join(context.args)
        await update.message.reply_text(
            f"🔍 Searching for _{query}_…", parse_mode="Markdown"
        )
        results = await web_search(query, max_results=5)
        if not results:
            await update.message.reply_text(
                "❌ Search unavailable right now. "
                "Make sure `duckduckgo-search` is installed, or try again later."
            )
            return
        msg = f'🔍 *Results for "{query}":*\n\n' + format_results(results)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(
            format_telegram_message(msg), parse_mode="MarkdownV2"
        )

    async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/research <topic> — web search + Claude synthesis of findings."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /research <topic>")
            return
        if claude_client is None:
            await update.message.reply_text(
                "❌ Claude not available for research synthesis."
            )
            return

        topic = " ".join(context.args)
        thread_id = getattr(update.message, "message_thread_id", None)
        chat_id = update.message.chat_id
        user_id = update.effective_user.id

        run_again_markup = make_run_again_keyboard(
            "research", {"topic": topic}, user_id
        )
        await run_research_flow(
            bot=context.bot,
            chat_id=chat_id,
            user_id=user_id,
            topic=topic,
            claude_client=claude_client,
            thread_id=thread_id,
            reply_markup=run_again_markup,
        )

    async def save_url_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/save-url <url> [note] — save a bookmark."""
        if update.message is None or update.effective_user is None:
            return
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
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        items = await fact_store.get_by_category(update.effective_user.id, "bookmark")
        if not items:
            await update.message.reply_text(
                "🔖 No bookmarks saved yet. Use /save-url <url> to add one."
            )
            return
        filt = " ".join(context.args).lower() if context.args else ""
        if filt:
            items = [b for b in items if filt in b["content"].lower()]
        if not items:
            await update.message.reply_text(f"🔖 No bookmarks matching '{filt}'.")
            return
        lines = [
            f"🔖 *Bookmarks{' (filtered)' if filt else ''} — {len(items)} item(s):*\n"
        ]
        for i, b in enumerate(items[:20], 1):
            lines.append(f"{i}. {b['content']}")
        if len(items) > 20:
            lines.append(f"…and {len(items) - 20} more")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def grocery_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /grocery-list              — show list (with IDs for remove-by-ID)
        /grocery-list add <items>  — add items (comma- or space-separated)
        /grocery-list done <item|id> — remove by name or ID (e.g. done 43)
        /grocery-list clear        — clear the whole list
        """
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if knowledge_store is None:
            await update.message.reply_text(
                "Grocery list requires memory (KnowledgeStore) to be configured."
            )
            return

        user_id = update.effective_user.id
        args = context.args or []
        sub = args[0].lower() if args else ""

        if sub == "add":
            items_raw = " ".join(args[1:]).strip()
            if not items_raw:
                await update.message.reply_text("Usage: /grocery-list add <items>")
                return
            # Normalise: support "milk, eggs" or "milk eggs"
            if "," in items_raw:
                items_raw = ",".join(
                    i.strip() for i in items_raw.split(",") if i.strip()
                )
            msg = await grocery_list_impl(knowledge_store, user_id, "add", items_raw)
            await update.message.reply_text(msg)

        elif sub == "done":
            items_raw = " ".join(args[1:]).strip()
            if not items_raw:
                await update.message.reply_text(
                    "Usage: /grocery-list done <item or ID>"
                )
                return
            msg = await grocery_list_impl(knowledge_store, user_id, "remove", items_raw)
            await update.message.reply_text(msg)

        elif sub == "clear":
            msg = await grocery_list_impl(knowledge_store, user_id, "clear", "")
            await update.message.reply_text(msg)

        else:
            msg = await grocery_list_impl(knowledge_store, user_id, "show", "")
            if "empty" in msg.lower():
                await update.message.reply_text(
                    "🛒 " + msg + "\nUse `/grocery-list add milk, eggs` to add.",
                    parse_mode="Markdown",
                )
                return
            await update.message.reply_text("🛒 " + msg)

    async def price_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/price-check <item> — search for current prices and synthesise with Claude."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /price-check <item>")
            return
        from ...web.search import web_search

        item = " ".join(context.args)
        await update.message.reply_text(
            f"🏷 Checking prices for _{item}_…", parse_mode="Markdown"
        )
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
            f"Source {i}: {r.get('title', '')}\n{r.get('body', '')}"
            for i, r in enumerate(results, 1)
        )
        try:
            analysis = await claude_client.complete(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Item: {item}\n\nSearch results:\n{snippets}\n\n"
                            "Extract and compare the prices mentioned. "
                            "List the best options with their prices and sources. "
                            "Be concise and factual."
                        ),
                    }
                ],
                system="You are a shopping assistant. Extract and compare prices from search results.",
                max_tokens=512,
            )
            msg = f"🏷 *Price check: {item}*\n\n{analysis}"
            if len(msg) > 4000:
                msg = msg[:4000] + "…"
            await update.message.reply_text(
                format_telegram_message(msg), parse_mode="MarkdownV2"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Could not analyse prices: {e}")

    async def _run_research_flow_for_callback(
        bot, chat_id: int, user_id: int, topic: str, thread_id: int | None = None
    ) -> None:
        """Bound run_research_flow for Run again callback (claude_client from closure)."""
        await run_research_flow(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            topic=topic,
            claude_client=claude_client,
            thread_id=thread_id,
            reply_markup=None,
        )

    return {
        "search": search_command,
        "research": research_command,
        "save-url": save_url_command,
        "bookmarks": bookmarks_command,
        "grocery-list": grocery_list_command,
        "price-check": price_check_command,
        "run_research_flow": _run_research_flow_for_callback,
    }
