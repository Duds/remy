"""
DuckDuckGo web search wrapper.
No API key required — uses the ddgs package (formerly duckduckgo-search).
"""

import asyncio
import logging

from ..config import get_settings

logger = logging.getLogger(__name__)

# primp (used internally by ddgs) emits a spurious WARNING on every request when
# the impersonation target it was compiled with isn't available in the installed
# version. The random fallback works fine — suppress the noise. (Bug 16)
logging.getLogger("primp.impersonate").setLevel(logging.ERROR)


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Return up to max_results text search results for query.
    Each result dict has: title, href, body.
    Returns [] on error (search unavailable, rate-limited, etc.)
    """

    settings = get_settings()
    timeout_s = settings.web_search_timeout_seconds

    def _sync() -> list[dict]:
        try:
            from ddgs import DDGS  # type: ignore[import]

            # DDGS(timeout=...) when supported — second layer of defence
            ddgs_kwargs: dict = {}
            try:
                import inspect

                sig = inspect.signature(DDGS.__init__)
                if "timeout" in sig.parameters:
                    ddgs_kwargs["timeout"] = min(20, int(timeout_s))
            except Exception:
                pass

            with DDGS(**ddgs_kwargs) as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except ImportError:
            logger.warning("ddgs not installed — web search unavailable")
            return []
        except Exception as e:
            logger.warning("DuckDuckGo search failed for %r: %s", query, e)
            return []

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_sync),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        try:
            from ..analytics.metrics import record_error

            record_error("web_search_timeout")
        except Exception:
            pass
        logger.warning(
            "DuckDuckGo search timed out after %.0fs for %r",
            timeout_s,
            query,
        )
        return []


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
