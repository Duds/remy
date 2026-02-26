"""
Researcher sub-agent — synthesises prior analyses into evidence-based questions
and identifies knowledge gaps the user should investigate further.

Note: drbot does not have live web search. The Researcher works with the context
provided by earlier agents and the user's own memory, surfacing what's unknown
and framing the right research questions rather than fetching live data.
"""

from __future__ import annotations

from .base_agent import SubAgent


class ResearcherAgent(SubAgent):
    name = "Researcher"
    role_description = (
        "Knowledge gap analysis — what to research, validate, and stress-test."
    )
    system_prompt = (
        "You are a research advisor on a personal AI board of directors. "
        "Your job is to review the analyses so far and identify: "
        "1. Key assumptions that need validation. "
        "2. Critical knowledge gaps — what the user doesn't yet know but needs to. "
        "3. Specific research questions or experiments to run. "
        "4. Credible sources or people to consult. "
        "You do NOT have live internet access, so do not claim to fetch real-time data. "
        "Instead, frame actionable research tasks the user can pursue. "
        "Be specific — 'Google X' is too vague; 'Search for academic papers on Y published "
        "after 2022' or 'Interview 3 potential customers about Z' is better. "
        "Format your response as a numbered list of research actions. "
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
            "As the Researcher, review the board analyses above. "
            "Identify the most important knowledge gaps and list specific "
            "research actions the user should take to validate the key assumptions."
        ).strip()
        result = await self._call_claude(prompt, max_tokens=400)
        return result
