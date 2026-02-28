"""Analytics tool executors."""

from __future__ import annotations

import logging
from datetime import timedelta, timezone, datetime as _dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_get_stats(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Show conversation usage statistics for a time period."""
    if registry._conversation_analyzer is None:
        return "Conversation analytics not available — ConversationAnalyzer not initialised."
    period = inp.get("period", "30d")
    try:
        stats = await registry._conversation_analyzer.get_stats(user_id, period)
        return registry._conversation_analyzer.format_stats_message(stats)
    except Exception as e:
        return f"Could not compute stats: {e}"


async def exec_get_goal_status(registry: ToolRegistry, user_id: int) -> str:
    """Show a goal tracking dashboard."""
    if registry._conversation_analyzer is None:
        return "Conversation analytics not available."
    since = _dt.now(timezone.utc) - timedelta(days=30)
    try:
        active = await registry._conversation_analyzer.get_active_goals_with_age(user_id)
        completed = await registry._conversation_analyzer.get_completed_goals_since(user_id, since)
        return registry._conversation_analyzer.format_goal_status_message(active, completed)
    except Exception as e:
        return f"Could not load goal status: {e}"


async def exec_generate_retrospective(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Generate a monthly retrospective."""
    if registry._conversation_analyzer is None:
        return "Conversation analytics not available."
    if registry._claude_client is None:
        return "Claude client not available for retrospective generation."
    period = inp.get("period", "30d")
    try:
        return await registry._conversation_analyzer.generate_retrospective(
            user_id, period, registry._claude_client
        )
    except Exception as e:
        return f"Could not generate retrospective: {e}"


async def exec_consolidate_memory(registry: ToolRegistry, user_id: int) -> str:
    """Review today's conversations and extract facts/goals worth persisting."""
    if registry._proactive_scheduler is None:
        return "Scheduler not available for memory consolidation."
    try:
        result = await registry._proactive_scheduler.run_memory_consolidation_now(user_id)
        if result.get("status") == "error":
            return f"❌ {result.get('message', 'Consolidation failed')}"

        facts = result.get("facts_stored", 0)
        goals = result.get("goals_stored", 0)

        if facts == 0 and goals == 0:
            return (
                "✅ Memory consolidation complete.\n\n"
                "No new facts or goals extracted from today's conversations. "
                "Either nothing worth persisting was discussed, or the information "
                "was already stored proactively during the conversation."
            )

        lines = ["✅ Memory consolidation complete:\n"]
        if facts > 0:
            lines.append(f"  Facts stored: {facts}")
        if goals > 0:
            lines.append(f"  Goals stored: {goals}")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not run memory consolidation: {e}"


async def exec_list_background_jobs(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """List recent background tasks and their status or results."""
    if registry._job_store is None:
        return "Job tracking not available."
    status_filter = inp.get("status_filter", "all")
    try:
        jobs = await registry._job_store.list_recent(user_id, limit=10)
    except Exception as e:
        return f"Could not fetch background jobs: {e}"
    if status_filter != "all":
        jobs = [j for j in jobs if j["status"] == status_filter]
    if not jobs:
        suffix = f" with status '{status_filter}'" if status_filter != "all" else ""
        return f"No background jobs{suffix} found."
    _STATUS_EMOJI = {"queued": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}
    lines = []
    for job in jobs:
        emoji = _STATUS_EMOJI.get(job["status"], "❓")
        result_preview = ""
        if job["result_text"]:
            preview = job["result_text"][:300].replace("\n", " ")
            result_preview = f"\n  Result: {preview}"
        lines.append(
            f'#{job["id"]} {job["job_type"]} {emoji} {job["status"]}'
            f'  (started {job["created_at"][:16]}){result_preview}'
        )
    return "\n\n".join(lines)


async def exec_get_costs(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Get estimated AI costs by provider and model for a time period."""
    if registry._conversation_analyzer is None:
        return "Analytics not available."

    db = getattr(registry._conversation_analyzer, '_db', None)
    if db is None:
        return "Cost tracking not available — database not configured."

    from ...analytics.costs import CostAnalyzer

    period = inp.get("period", "30d")
    valid_periods = {"7d", "30d", "90d", "all"}
    if period not in valid_periods:
        period = "30d"

    try:
        cost_analyzer = CostAnalyzer(db)
        summary = await cost_analyzer.get_cost_summary(user_id, period)
        return cost_analyzer.format_cost_message(summary)
    except Exception as e:
        return f"Could not calculate costs: {e}"
