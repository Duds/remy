"""
Researcher sub-agent — web search + synthesis.

Runs 1–3 web searches in parallel and synthesises results into a structured report.
Used by Agent Creator for research tasks (US-multi-agent-architecture PBI-5).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..web.search import web_search, format_results

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_MAX_SEARCHES = 3
_MAX_RESULTS_PER_SEARCH = 5


async def run_research(
    topic: str,
    *,
    claude_client: "ClaudeClient | None" = None,
    user_context: str = "",
) -> str:
    """
    Run web research on a topic: search + synthesise into a report.

    Args:
        topic: Research question or topic
        claude_client: Optional Claude client for synthesis (uses complete())
        user_context: Optional XML context (goals, facts) for personalisation

    Returns:
        Formatted Markdown report
    """
    # Run 1–3 searches (same query; in future could split into sub-queries)
    tasks = [
        web_search(topic, max_results=_MAX_RESULTS_PER_SEARCH)
        for _ in range(min(_MAX_SEARCHES, 1))  # 1 search for now to avoid rate limits
    ]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[dict] = []
    for r in results_list:
        if isinstance(r, list):
            all_results.extend(r)
        elif isinstance(r, Exception):
            logger.warning("Web search failed: %s", r)

    if not all_results:
        return f"**Research: {topic}**\n\n_No web results found._ Try rephrasing or check connectivity."

    formatted = format_results(all_results[:15], max_body=250)

    if claude_client is None:
        return (
            f"**Research: {topic}**\n\n"
            f"Found {len(all_results)} result(s):\n\n{formatted}"
        )

    # Synthesise with Claude
    system = (
        "You are a research assistant. Synthesise the provided web search results "
        "into a clear, concise report. Use bullet points and bold for key findings. "
        "Keep it under 1500 words. Do not invent information not present in the results."
    )
    user_content = (
        f"Topic: {topic}\n\n"
        f"<search_results>\n{formatted}\n</search_results>"
    )
    if user_context:
        user_content = f"<user_context>\n{user_context}\n</user_context>\n\n{user_content}"

    try:
        synthesis = await claude_client.complete(
            messages=[{"role": "user", "content": user_content}],
            system=system,
            max_tokens=1500,
        )
        return f"**Research: {topic}**\n\n{synthesis}"
    except Exception as e:
        logger.warning("Research synthesis failed: %s", e)
        return (
            f"**Research: {topic}**\n\n"
            f"Synthesis failed. Raw results:\n\n{formatted}"
        )
