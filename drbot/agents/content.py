"""
Content sub-agent — messaging, narrative, and communication advice.
"""

from __future__ import annotations

from .base_agent import SubAgent


class ContentAgent(SubAgent):
    name = "Content"
    role_description = "Messaging, narrative framing, and communication strategy."
    system_prompt = (
        "You are a content and communications advisor on a personal AI board of directors. "
        "Your job is to analyse the user's topic through a communications lens: "
        "craft the core message, identify the right audience and tone, "
        "and suggest concrete content or communication actions. "
        "Think about story, positioning, and how ideas land with people. "
        "Be specific — propose actual headline ideas, copy angles, or channel strategies "
        "rather than vague advice. "
        "Format your response as concise bullet points or short paragraphs. "
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
            "As the Content advisor, provide your communications and messaging "
            "recommendations. Consider how the strategic priorities above should be "
            "communicated."
        ).strip()
        result = await self._call_claude(prompt, max_tokens=400)
        return result
