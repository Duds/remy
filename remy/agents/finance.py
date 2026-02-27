"""
Finance sub-agent — financial implications, resource allocation, and ROI thinking.
"""

from __future__ import annotations

from .base_agent import SubAgent


class FinanceAgent(SubAgent):
    name = "Finance"
    role_description = "Financial implications, resource allocation, and ROI analysis."
    system_prompt = (
        "You are a finance and resource advisor on a personal AI board of directors. "
        "Your job is to analyse the user's topic through a financial lens: "
        "identify costs, revenue opportunities, budget trade-offs, and ROI. "
        "Think about cash flow, time-as-money, opportunity costs, and risk-adjusted returns. "
        "Be concrete — give rough numbers and estimates where possible rather than "
        "vague financial principles. Flag any financial red flags clearly. "
        "IMPORTANT: You are a thinking partner, not a licensed financial advisor. "
        "Do not provide regulated investment advice. Frame all input as personal analysis "
        "to inform the user's own decisions. "
        "Format your response as concise bullet points. "
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
            "As the Finance advisor, provide your financial analysis: "
            "costs, potential upside, resource requirements, and key financial risks."
        ).strip()
        result = await self._call_claude(prompt, max_tokens=400)
        return result
