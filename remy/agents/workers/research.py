"""Research worker — web search + structured findings (SAD v10 §11.4).

Validates the full orchestrator → worker → heartbeat loop.
No dependencies beyond Remy's existing web_search tool and MistralClient.

Input task_context keys:
  topic (str, required)   — core research question
  scope (str, optional)   — additional context / constraints
  depth_limit (int)       — max spawn depth for sub-topics (inherited from runner)

Output: JSON string matching the research.md skill schema:
  {summary, findings, gaps, sources, relevant_goals}
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from ...config import settings

if TYPE_CHECKING:
    from ...memory.database import DatabaseManager
    from ..runner import TaskRunner

logger = logging.getLogger(__name__)


class ResearchAgent:
    """
    Researches a topic using web search and produces structured JSON findings.

    Uses Remy's existing web_search infrastructure — does not reimplement search.
    Can spawn sub-topic children via TaskRunner up to MAX_CHILDREN / MAX_DEPTH.
    """

    def __init__(self, db: "DatabaseManager", runner: "TaskRunner") -> None:
        self._db = db
        self._runner = runner

    async def run(
        self,
        task_id: str,
        task_context: dict,
        skill_context: str = "",
    ) -> str:
        """Execute the research task and return raw JSON findings."""
        topic = (task_context.get("topic") or "").strip()
        scope = (task_context.get("scope") or "").strip()

        if not topic:
            return json.dumps(
                {
                    "summary": "No topic provided.",
                    "findings": [],
                    "gaps": ["task_context missing required 'topic' key"],
                    "sources": [],
                    "relevant_goals": [],
                }
            )

        logger.info("ResearchAgent task_id=%s topic=%r", task_id, topic[:80])

        search_results = await self._gather_search_results(topic, scope)
        model = getattr(settings, "subagent_worker_model", "mistral")
        system_prompt = (
            skill_context.strip()
            if skill_context
            else "You are a research assistant. Return structured JSON only."
        )
        user_prompt = (
            f"Research topic: {topic}\n"
            + (f"Scope: {scope}\n" if scope else "")
            + f"\nWeb search results:\n{search_results}\n\n"
            "Return structured JSON with keys: "
            "summary, findings, gaps, sources, relevant_goals."
        )

        raw_output = await _call_mistral(system_prompt, user_prompt, model)
        return raw_output

    async def _gather_search_results(self, topic: str, scope: str) -> str:
        """Run up to 2 web searches and concatenate formatted results."""
        from ...web.search import format_results, web_search

        queries = [topic]
        if scope and scope.lower() != topic.lower():
            queries.append(f"{topic} {scope}")

        parts: list[str] = []
        for query in queries[:2]:
            try:
                results = await web_search(query, max_results=5)
                if results:
                    parts.append(f"Query: {query}\n" + format_results(results))
            except Exception as exc:
                logger.warning("Web search failed for %r: %s", query, exc)

        return "\n\n---\n\n".join(parts) if parts else "No search results available."


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _call_mistral(system: str, user: str, model: str) -> str:
    """Collect a streaming Mistral response into a single string."""
    from ...ai.mistral_client import MistralClient

    client = MistralClient()
    chunks: list[str] = []
    async for chunk in client.stream_chat(
        messages=[{"role": "user", "content": f"{system}\n\n{user}"}],
        model=model,
        max_tokens=2048,
    ):
        chunks.append(chunk)
    return "".join(chunks)
