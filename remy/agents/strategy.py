"""
Strategy sub-agent — big-picture thinking, prioritisation, and roadmap advice.
"""

from __future__ import annotations

from .base_agent import SubAgent


class StrategyAgent(SubAgent):
    name = "Strategy"
    role_description = "Big-picture thinking, prioritisation, and long-term planning."
    system_prompt = (
        "You are a strategic advisor on a personal AI board of directors. "
        "Your job is to analyse the user's topic through a strategic lens: "
        "identify the highest-leverage opportunities, surface hidden risks, "
        "and propose a clear prioritised roadmap. "
        "Be direct, opinionated, and specific. Avoid generic advice. "
        "Format your response as concise bullet points or a numbered list. "
        "Limit your response to 250 words."
    )

    async def analyze(
        self,
        topic: str,
        thread: list[dict],
        user_context: str = "",
    ) -> str:
        context_block = self._build_context_block(thread, user_context)
        prompt = (
            f"Topic: {topic}\n\n"
            f"{context_block}\n\n"
            "As the Strategy advisor, provide your strategic assessment and "
            "top-priority recommendations."
        ).strip()
        result = await self._call_claude(prompt, max_tokens=400)
        return result
