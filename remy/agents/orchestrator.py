"""
Board Orchestrator — runs sub-agents sequentially and formats the final report.

Execution order:
    Strategy → Content → Finance → Researcher → Critic (always last)

Each agent receives the full thread of prior analyses so it can build on them.
The Critic always runs last and synthesises a Board Verdict.

The final report is formatted for Telegram (MarkdownV2 safe-ish; uses bold
section headers via *Agent Name* syntax that works with parse_mode="Markdown").
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, AsyncIterator

from .content import ContentAgent
from .critic import CriticAgent
from .finance import FinanceAgent
from .researcher import ResearcherAgent
from .strategy import StrategyAgent

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient
    from .base_agent import SubAgent

logger = logging.getLogger(__name__)

# Telegram message length limit
_TELEGRAM_MAX = 4096

# Section separator used in the report
_SECTION_SEP = "\n\n" + "─" * 30 + "\n\n"


class BoardOrchestrator:
    """
    Runs the board of directors sequentially and returns a formatted report.

    Usage::

        orchestrator = BoardOrchestrator(claude_client)
        async for chunk in orchestrator.run_board_streaming(topic, user_context):
            # send each chunk to Telegram (handles 4096 limit)
            ...

        # Or collect the full report:
        report = await orchestrator.run_board(topic, user_context)
    """

    def __init__(self, claude_client: "ClaudeClient") -> None:
        self._client = claude_client
        # Critic MUST be last
        self._agents: list["SubAgent"] = [
            StrategyAgent(claude_client),
            ContentAgent(claude_client),
            FinanceAgent(claude_client),
            ResearcherAgent(claude_client),
            CriticAgent(claude_client),
        ]

    async def run_board(
        self,
        topic: str,
        user_context: str = "",
    ) -> str:
        """
        Run all agents sequentially and return the full formatted board report.

        Args:
            topic:        The board topic from the user's /board command.
            user_context: Optional XML user memory block (goals, facts) for
                          personalised advice.

        Returns:
            Formatted Markdown report string ready to send via Telegram.
        """
        thread: list[dict] = []
        results: list[tuple[str, str]] = []  # (agent_name, analysis)

        for agent in self._agents:
            logger.info("[Board] Running agent: %s", agent.name)
            try:
                analysis = await agent.analyze(topic, thread, user_context)
            except Exception as exc:
                logger.error("[Board] Agent %s failed: %s", agent.name, exc)
                analysis = f"[{agent.name} analysis unavailable: {exc}]"

            results.append((agent.name, analysis))
            # Append to thread for next agents to read
            thread.append({
                "role": "assistant",
                "content": f"*{agent.name}*: {analysis}",
            })

        return self._format_report(topic, results)

    async def run_board_streaming(
        self,
        topic: str,
        user_context: str = "",
    ) -> AsyncIterator[str]:
        """
        Async generator that yields progress updates as each agent completes.

        Yields strings in order:
            - "🟡 Running Strategy…\n"
            - full Strategy analysis section
            - "🟡 Running Content…\n"
            - full Content section
            - … (etc. for each agent)
            - final Board Verdict section
        """
        thread: list[dict] = []
        results: list[tuple[str, str]] = []
        agent_count = len(self._agents)

        for idx, agent in enumerate(self._agents, 1):
            emoji = "🟣" if agent.name == "Critic" else "🟡"
            yield f"{emoji} *{agent.name}* ({idx}/{agent_count})…\n"
            # Give the event loop a tick to let the progress update send
            await asyncio.sleep(0)

            try:
                analysis = await agent.analyze(topic, thread, user_context)
            except Exception as exc:
                logger.error("[Board] Agent %s failed: %s", agent.name, exc)
                analysis = f"[{agent.name} analysis unavailable: {exc}]"

            results.append((agent.name, analysis))
            thread.append({
                "role": "assistant",
                "content": f"*{agent.name}*: {analysis}",
            })

            # Yield this agent's section immediately
            section = self._format_section(agent.name, analysis)
            yield section

        # Final summary header already embedded in Critic output; no extra needed.

    # ------------------------------------------------------------------ #
    # Formatting helpers                                                   #
    # ------------------------------------------------------------------ #

    def _format_section(self, agent_name: str, analysis: str) -> str:
        """Format a single agent's section."""
        return f"\n*📋 {agent_name}*\n{analysis}\n"

    def _format_report(
        self,
        topic: str,
        results: list[tuple[str, str]],
    ) -> str:
        """Assemble the full board report from individual agent results."""
        header = f"*🏛 Board of Directors Report*\n_Topic: {topic}_\n"
        sections = [self._format_section(name, analysis) for name, analysis in results]
        return header + _SECTION_SEP.join([""] + sections)

    @staticmethod
    def split_for_telegram(text: str) -> list[str]:
        """
        Split a long report into Telegram-safe chunks (≤ 4096 chars each).
        Tries to split on double-newlines to avoid cutting in the middle of a
        paragraph.
        """
        if len(text) <= _TELEGRAM_MAX:
            return [text]

        chunks: list[str] = []
        current = ""

        for paragraph in text.split("\n\n"):
            candidate = current + ("\n\n" if current else "") + paragraph
            if len(candidate) <= _TELEGRAM_MAX:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                # If a single paragraph exceeds the limit, hard-split it
                if len(paragraph) > _TELEGRAM_MAX:
                    for i in range(0, len(paragraph), _TELEGRAM_MAX):
                        chunks.append(paragraph[i : i + _TELEGRAM_MAX])
                    current = ""
                else:
                    current = paragraph

        if current:
            chunks.append(current)

        return chunks or [text[:_TELEGRAM_MAX]]
