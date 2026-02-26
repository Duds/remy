"""
DuckDuckGo web search wrapper.
No API key required — uses the ddgs package (formerly duckduckgo-search).
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Return up to max_results text search results for query.
    Each result dict has: title, href, body.
    Returns [] on error (search unavailable, rate-limited, etc.)
    """
    def _sync() -> list[dict]:
        try:
            from ddgs import DDGS  # type: ignore[import]
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except ImportError:
            logger.warning("ddgs not installed — web search unavailable")
            return []
        except Exception as e:
            logger.warning("DuckDuckGo search failed for %r: %s", query, e)
            return []

    return await asyncio.to_thread(_sync)


def format_results(results: list[dict], max_body: int = 200) -> str:
    """Format search results as a Markdown list."""
    if not results:
        return "_No results found._"
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("href", "")
        body = (r.get("body") or "").strip()
        if len(body) > max_body:
            body = body[:max_body] + "…"
        lines.append(f"*{i}. {title}*\n   {url}\n   _{body}_")
    return "\n\n".join(lines)
