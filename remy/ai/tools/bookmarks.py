"""Bookmark tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)

BOOKMARK_TAGS = ("preferences", "work", "personal")


def _is_valid_url(url: str) -> bool:
    """Check URL has a valid scheme for bookmarking."""
    return url.startswith(("http://", "https://"))


async def exec_save_bookmark(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Save a URL as a bookmark with optional tag."""
    url = inp.get("url", "").strip()
    note = inp.get("note", "").strip()
    tag = (inp.get("tag") or "").strip().lower()

    if not url:
        return "Please provide a URL to bookmark."

    if not _is_valid_url(url):
        return "Please provide a valid URL (must start with http:// or https://)."

    if tag and tag not in BOOKMARK_TAGS:
        return f"Invalid tag. Use one of: {', '.join(BOOKMARK_TAGS)}"

    content = f"{url} — {note}" if note else url
    metadata: dict = {"category": "bookmark"}
    if tag:
        metadata["tag"] = tag

    if registry._knowledge_store is None:
        return "Memory not available."

    await registry._knowledge_store.add_item(
        user_id, "fact", content, metadata
    )
    out = f"🔖 Bookmark saved: {content}"
    if tag:
        out += f" (tag: {tag})"
    return out


async def exec_list_bookmarks(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """List saved bookmarks with optional filter and tag."""
    if registry._fact_store is None and registry._knowledge_store is None:
        return "Memory not available."

    filt = inp.get("filter", "").strip().lower()
    tag_filter = (inp.get("tag") or inp.get("filter", "")).strip().lower()
    if tag_filter not in BOOKMARK_TAGS:
        tag_filter = ""

    if registry._knowledge_store is not None:
        items = await registry._knowledge_store.get_by_type(user_id, "fact", limit=50)
        bookmarks = [
            {"content": i.content, "tag": i.metadata.get("tag")}
            for i in items
            if i.metadata.get("category") == "bookmark"
        ]
        if tag_filter:
            bookmarks = [b for b in bookmarks if b.get("tag") == tag_filter]
    elif registry._fact_store is not None:
        bookmarks = await registry._fact_store.get_by_category(user_id, "bookmark")
        bookmarks = [{"content": b.get("content", "")} for b in bookmarks]
    else:
        bookmarks = []

    if not bookmarks:
        return "🔖 No bookmarks saved yet. Use save_bookmark to add one."

    if filt and not tag_filter:
        bookmarks = [b for b in bookmarks if filt in b.get("content", "").lower()]

    if not bookmarks:
        return f"🔖 No bookmarks matching '{filt}'."

    suffix = ""
    if tag_filter:
        suffix = f" (tag: {tag_filter})"
    elif filt:
        suffix = " (filtered)"
    lines = [f"🔖 Bookmarks{suffix} — {len(bookmarks)} item(s):\n"]
    for i, b in enumerate(bookmarks[:20], 1):
        lines.append(f"{i}. {b.get('content', '')}")
    if len(bookmarks) > 20:
        lines.append(f"…and {len(bookmarks) - 20} more")

    return "\n".join(lines)
