"""
Leaf agents — single-tool, single-call, 15s timeout (US-multi-agent-architecture PBI-1–4).

Leaves are used by sub-agents (Researcher, Ops) for one-shot tool execution.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient
    from ..ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

LEAF_TIMEOUT_SECONDS = 15


async def run_leaf(
    task: str,
    tool_name: str,
    tool_input: dict,
    *,
    user_id: int,
    registry: "ToolRegistry",
    claude_client: "ClaudeClient",
    system_prompt: str = "You have one tool. Use it to fulfil the user request and return a concise result.",
) -> dict:
    """
    Run a single-tool leaf: one Claude call with one tool, 15s hard timeout.

    Returns dict with keys: success, output, error (if failed).
    """
    from ..ai.claude_client import TextChunk, ToolStatusChunk, ToolTurnComplete

    messages = [{"role": "user", "content": task.strip() or "Proceed."}]
    # Only this tool
    allowed = [tool_name]
    from .subagent_runner import FilteredToolRegistry

    filtered = FilteredToolRegistry(registry, allowed)
    final_text: list[str] = []
    in_tool = False

    try:
        in_tool_ref: list[bool] = [False]

        async def _run() -> None:
            async for event in claude_client.stream_with_tools(
                messages=messages,
                tool_registry=filtered,
                user_id=user_id,
                system=system_prompt,
                max_iterations=1,
            ):
                if isinstance(event, TextChunk) and not in_tool_ref[0]:
                    final_text.append(event.text)
                elif isinstance(event, ToolStatusChunk):
                    in_tool_ref[0] = True
                elif isinstance(event, ToolTurnComplete):
                    in_tool_ref[0] = False

        await asyncio.wait_for(
            _run(),
            timeout=LEAF_TIMEOUT_SECONDS,
        )
        return {
            "success": True,
            "output": "".join(final_text).strip() or "(no text)",
        }
    except asyncio.TimeoutError:
        logger.warning("Leaf %s timed out for user %d", tool_name, user_id)
        return {
            "success": False,
            "output": "",
            "error": f"Leaf timed out after {LEAF_TIMEOUT_SECONDS}s",
        }
    except Exception as e:
        logger.warning("Leaf %s failed: %s", tool_name, e)
        return {
            "success": False,
            "output": "",
            "error": str(e),
        }


async def run_web_search_leaf(
    query: str,
    max_results: int = 5,
    *,
    user_id: int,
    registry: "ToolRegistry",
    claude_client: "ClaudeClient",
) -> dict:
    """PBI-2: One-shot web search leaf. Returns { query, summary, sources[] }-style result."""
    task = f"Search the web for: {query}. Return a brief summary and list the sources (max {max_results} results)."
    result = await run_leaf(
        task,
        "web_search",
        {"query": query, "max_results": max_results},
        user_id=user_id,
        registry=registry,
        claude_client=claude_client,
    )
    if result.get("success"):
        result["query"] = query
        result["summary"] = result.get("output", "")
    return result


async def run_file_read_leaf(
    path: str,
    extraction_hint: str = "",
    *,
    user_id: int,
    registry: "ToolRegistry",
    claude_client: "ClaudeClient",
) -> dict:
    """PBI-3: One-shot file read leaf. Returns { path, extracted_content, raw_length }."""
    task = f"Read the file at: {path}. "
    if extraction_hint:
        task += f"Focus on: {extraction_hint}. "
    task += "Return the relevant content (or a short summary if very long)."
    result = await run_leaf(
        task,
        "read_file",
        {"path": path},
        user_id=user_id,
        registry=registry,
        claude_client=claude_client,
    )
    if result.get("success"):
        result["path"] = path
        result["extracted_content"] = result.get("output", "")
    return result


async def run_gmail_search_leaf(
    query: str,
    max_results: int = 5,
    include_body: bool = False,
    *,
    user_id: int,
    registry: "ToolRegistry",
    claude_client: "ClaudeClient",
) -> dict:
    """PBI-4: One-shot Gmail search leaf. Returns { results[], count }-style result."""
    task = f"Search Gmail for: {query}. Return up to {max_results} matching emails (subject/sender/snippet)."
    result = await run_leaf(
        task,
        "search_gmail",
        {"query": query, "max_results": max_results},
        user_id=user_id,
        registry=registry,
        claude_client=claude_client,
    )
    if result.get("success"):
        result["summary"] = result.get("output", "")
    return result
