"""Google Docs tool executors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_read_gdoc(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Read a Google Doc by ID or URL."""
    if registry._docs is None:
        return (
            "Google Docs not configured. "
            "Run scripts/setup_google_auth.py to set it up."
        )
    raw = inp.get("doc_id_or_url", "").strip()
    if not raw:
        return "No document ID or URL provided."

    try:
        title, content = await registry._docs.read_document(raw)
    except Exception as e:
        return f"Could not read document: {e}"

    if not content:
        return f"Document '{title}' is empty."
    if len(content) > 8000:
        content = content[:8000] + "\n\n[… truncated — document is longer]"
    return f"Google Doc: {title}\n\n{content}"


async def exec_append_to_gdoc(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Append text to a Google Doc."""
    if registry._docs is None:
        return "Google Docs not configured."

    doc_id_or_url = inp.get("doc_id_or_url", "").strip()
    text = inp.get("text", "").strip()

    if not doc_id_or_url:
        return "Please provide a Google Doc ID or URL."
    if not text:
        return "Please provide text to append."

    try:
        await registry._docs.append_text(doc_id_or_url, text)
        return "✅ Text appended to document."
    except Exception as e:
        return f"Could not append to doc: {e}"
