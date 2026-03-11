"""
Agent Creator — classifies tasks and spawns specialist sub-agents.

Builds sub-agent specs and hands off via BackgroundTaskRunner (US-agent-creator).
Board is excluded; only Researcher, Coder, Ops, Analyst (Researcher implemented first).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


class SubAgentType(str, Enum):
    """Sub-agent types the Creator can spawn."""

    RESEARCH = "research"
    CODER = "coder"
    OPS = "ops"
    ANALYST = "analyst"


@dataclass
class SubAgentSpec:
    """Spec for a sub-agent run."""

    type: SubAgentType
    system_prompt: str
    allowed_tools: list[str]
    max_turns: int
    timeout_s: int


# Heuristic keywords for classification (no LLM call)
_RESEARCH_PATTERNS = re.compile(
    r"\b(research|look up|search for|find out|summarise|summarize|"
    r"what is|who is|when did|how does|web search|google|"
    r"recent news|latest on|current (state|status)|"
    r"compare .* (vs|versus|and)|find (info|information)|"
    r"learn about|read about)\b",
    re.IGNORECASE,
)
_CODER_PATTERNS = re.compile(
    r"\b(code|script|run (python|code)|execute|debug|"
    r"fix (this|the) (code|bug)|implement|refactor)\b",
    re.IGNORECASE,
)
_OPS_PATTERNS = re.compile(
    r"\b(read file|search gmail|calendar|email|label|archive|trash)\b",
    re.IGNORECASE,
)
_ANALYST_PATTERNS = re.compile(
    r"\b(calculate|analyse|analyze|data|spreadsheet|numbers)\b",
    re.IGNORECASE,
)


class AgentCreator:
    """
    Classifies task descriptions and spawns specialist sub-agents.
    Board is never chosen — Board = explicit user opt-in only.
    """

    def __init__(
        self,
        claude_client=None,
        tool_registry=None,
    ) -> None:
        self._claude = claude_client
        self._registry = tool_registry

    def classify(self, task_description: str) -> SubAgentType | None:
        """
        Classify task intent. Returns SubAgentType or None if unclear.
        Uses heuristics; later can add cheap Haiku call.
        """
        text = (task_description or "").strip()
        if not text:
            return None
        if _RESEARCH_PATTERNS.search(text):
            return SubAgentType.RESEARCH
        if _CODER_PATTERNS.search(text):
            return SubAgentType.CODER
        if _OPS_PATTERNS.search(text):
            return SubAgentType.OPS
        if _ANALYST_PATTERNS.search(text):
            return SubAgentType.ANALYST
        return None

    def build_spec(
        self, task_type: SubAgentType, task_description: str
    ) -> SubAgentSpec:
        """Build a sub-agent spec from type and task (template-based)."""
        if task_type == SubAgentType.RESEARCH:
            return SubAgentSpec(
                type=SubAgentType.RESEARCH,
                system_prompt="You are a research specialist.",
                allowed_tools=["web_search"],
                max_turns=5,
                timeout_s=120,
            )
        if task_type == SubAgentType.CODER:
            return SubAgentSpec(
                type=SubAgentType.CODER,
                system_prompt="You are a coding specialist.",
                allowed_tools=["run_python", "run_claude_code"],
                max_turns=5,
                timeout_s=60,
            )
        if task_type == SubAgentType.OPS:
            return SubAgentSpec(
                type=SubAgentType.OPS,
                system_prompt="You are an ops specialist (file, email, calendar).",
                allowed_tools=[
                    "read_file",
                    "list_directory",
                    "search_gmail",
                    "calendar_events",
                ],
                max_turns=5,
                timeout_s=60,
            )
        if task_type == SubAgentType.ANALYST:
            return SubAgentSpec(
                type=SubAgentType.ANALYST,
                system_prompt="You are a data analyst.",
                allowed_tools=["run_python"],
                max_turns=5,
                timeout_s=60,
            )
        raise ValueError(f"Unknown sub-agent type: {task_type}")

    async def run_research(self, topic: str, user_context: str = "") -> str:
        """
        Run Researcher sub-agent inline and return the report.
        Use spawn_and_hand_off() for fire-and-forget delivery.
        """
        from .researcher_subagent import run_research

        return await run_research(
            topic,
            claude_client=self._claude,
            user_context=user_context,
        )

    async def spawn_and_hand_off(
        self,
        spec: SubAgentSpec,
        task_description: str,
        user_id: int,
    ) -> str:
        """
        Spawn the sub-agent in the background and return a confirmation message.
        Uses BackgroundTaskRunner + BackgroundJobStore; result is delivered via Telegram.

        Requires the registry to have request-scoped _current_bot, _current_chat_id
        (set by the chat handler). If missing, falls back to inline run for research only.
        """
        from .background import BackgroundTaskRunner
        from .subagent_runner import run_subagent
        from telegram.constants import ChatAction

        registry = self._registry
        job_store = getattr(registry, "_job_store", None)
        bot = getattr(registry, "_current_bot", None)
        chat_id = getattr(registry, "_current_chat_id", None)
        thread_id = getattr(registry, "_current_thread_id", None)

        if not job_store or not bot or chat_id is None:
            # Fallback: run research inline if that's the only type we can do without bot
            if spec.type == SubAgentType.RESEARCH and task_description.strip():
                return await self.run_research(task_description.strip())
            return (
                "I can't start a background task right now. "
                "Try again from a chat so I can message you when it's done."
            )

        job_id = await job_store.create(
            user_id, spec.type.value, task_description.strip() or "Task"
        )

        async def _coro() -> str:
            return await run_subagent(
                spec,
                task_description,
                user_id,
                registry,
                self._claude,
            )

        try:
            from ..bot.working_message import WorkingMessage

            working_message = WorkingMessage(bot, chat_id, thread_id=thread_id)
            await working_message.start()
        except Exception:
            working_message = None

        runner = BackgroundTaskRunner(
            bot,
            chat_id,
            job_store=job_store,
            job_id=job_id,
            working_message=working_message,
            thread_id=thread_id,
            chat_action=ChatAction.UPLOAD_DOCUMENT,
        )
        asyncio.create_task(
            runner.run(
                asyncio.wait_for(
                    _coro(), timeout=spec.timeout_s
                ),
                label=spec.type.value,
            )
        )

        labels = {
            SubAgentType.RESEARCH: "researching that for you",
            SubAgentType.CODER: "working on that code",
            SubAgentType.OPS: "handling that",
            SubAgentType.ANALYST: "running that analysis",
        }
        return f"On it — {labels.get(spec.type, spec.type.value)} 🔄"
