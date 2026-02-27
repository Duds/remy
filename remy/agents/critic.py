"""
Critic sub-agent — steelmanned counter-arguments, devil's advocate, and synthesis.
Always runs last so it can review all prior analyses.
"""

from __future__ import annotations

from .base_agent import SubAgent


class CriticAgent(SubAgent):
    name = "Critic"
    role_description = (
        "Devil's advocate — challenges assumptions and synthesises a final verdict."
    )
    system_prompt = (
        "You are the Critic on a personal AI board of directors. "
        "You ALWAYS run last and your job has two parts:\n"
        "1. CHALLENGE: Steelman the strongest counter-arguments to the board's consensus. "
        "What are the board getting wrong? What are they overlooking? "
        "What's the most likely way this all fails? Be pointed and specific.\n"
        "2. SYNTHESISE: After the challenges, write a short 'Board Verdict' — "
        "a 3-5 sentence plain-language summary of the key action the user should take, "
        "the biggest risk to manage, and the most important open question.\n"
        "Format: Use '## Challenges' and '## Board Verdict' as section headers. "
        "Limit your full response to 300 words."
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
            "As the Critic — the final voice on the board — challenge the analyses above "
            "and then deliver the Board Verdict."
        ).strip()
        result = await self._call_claude(prompt, max_tokens=500)
        return result
