"""Bookmark tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_save_bookmark(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Save a URL as a bookmark."""
    url = inp.get("url", "").strip()
    note = inp.get("note", "").strip()

    if not url:
        return "Please provide a URL to bookmark."

    if registry._fact_store is None and registry._knowledge_store is None:
        return "Memory not available."

    content = f"{url} — {note}" if note else url

    if registry._knowledge_store is not None:
        await registry._knowledge_store.add(
            user_id=user_id,
            entity_type="fact",
            content=content,
            metadata={"category": "bookmark"},
        )
    elif registry._fact_store is not None:
        await registry._fact_store.add(user_id, "bookmark", content)

    return f"🔖 Bookmark saved: {content}"


async def exec_list_bookmarks(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """List saved bookmarks with optional filter."""
    if registry._fact_store is None and registry._knowledge_store is None:
        return "Memory not available."

    filt = inp.get("filter", "").strip().lower()

    if registry._knowledge_store is not None:
        items = await registry._knowledge_store.query(
            user_id=user_id,
            entity_type="fact",
            metadata_filter={"category": "bookmark"},
            limit=50,
        )
        bookmarks = [{"content": i.get("content", "")} for i in items]
    elif registry._fact_store is not None:
        bookmarks = await registry._fact_store.get_by_category(user_id, "bookmark")
    else:
        bookmarks = []

    if not bookmarks:
        return "🔖 No bookmarks saved yet. Use save_bookmark to add one."

    if filt:
        bookmarks = [b for b in bookmarks if filt in b.get("content", "").lower()]

    if not bookmarks:
        return f"🔖 No bookmarks matching '{filt}'."

    lines = [f"🔖 Bookmarks{' (filtered)' if filt else ''} — {len(bookmarks)} item(s):\n"]
    for i, b in enumerate(bookmarks[:20], 1):
        lines.append(f"{i}. {b.get('content', '')}")
    if len(bookmarks) > 20:
        lines.append(f"…and {len(bookmarks) - 20} more")

    return "\n".join(lines)
