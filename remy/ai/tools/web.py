"""Web search tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_web_search(registry: ToolRegistry, inp: dict) -> str:
    """Search the web using DuckDuckGo and return results."""
    from ...web.search import web_search, format_results
    query = inp.get("query", "").strip()
    if not query:
        return "No search query provided."
    max_results = min(int(inp.get("max_results", 5)), 10)
    results = await web_search(query, max_results=max_results)
    if not results:
        return "Search unavailable or no results. Try a different query."
    return f"Search results for '{query}':\n\n" + format_results(results)


async def exec_price_check(registry: ToolRegistry, inp: dict) -> str:
    """Search for current prices of a product or service."""
    from ...web.search import web_search, format_results
    item = inp.get("item", "").strip()
    if not item:
        return "No item specified."
    query = f"{item} price Australia 2025"
    results = await web_search(query, max_results=5)
    if not results:
        return f"Could not find price information for '{item}'."
    return f"Price check for '{item}':\n\n" + format_results(results)
