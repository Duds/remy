"""
Phase 6: Conversation analytics engine.

ConversationAnalyzer reads JSONL session files and the database to produce:
  - Usage statistics (message counts, active days, model breakdown)
  - Goal status dashboard (active goals with age, completed goals)
  - Monthly retrospective (Claude-generated summary)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from ..memory.conversations import ConversationStore
from ..memory.database import DatabaseManager

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

# Days without update before a goal is flagged as stale (matches evening check-in)
_STALE_DAYS = 3


def _parse_period(period: str) -> tuple[datetime, datetime]:
    """Parse period string ('7d', '30d', '90d', 'all') to UTC (start, end)."""
    now = datetime.now(timezone.utc)
    p = period.lower().strip()
    if p == "7d":
        return now - timedelta(days=7), now
    if p in ("30d", "month"):
        return now - timedelta(days=30), now
    if p == "90d":
        return now - timedelta(days=90), now
    if p == "all":
        return datetime(2020, 1, 1, tzinfo=timezone.utc), now
    if p.endswith("d") and p[:-1].isdigit():
        return now - timedelta(days=int(p[:-1])), now
    return now - timedelta(days=30), now


def _period_label(period: str) -> str:
    labels = {
        "7d": "the last 7 days",
        "30d": "the last 30 days",
        "month": "the last 30 days",
        "90d": "the last 90 days",
        "all": "all time",
    }
    return labels.get(period.lower(), f"the last {period}")


class ConversationAnalyzer:
    """Provides analytics over JSONL session files and the goals table."""

    def __init__(
        self,
        conv_store: ConversationStore,
        db: DatabaseManager,
    ) -> None:
        self._conv_store = conv_store
        self._db = db

    async def get_stats(self, user_id: int, period: str = "30d") -> dict[str, Any]:
        """
        Parse JSONL sessions and compute usage statistics for the given period.

        Session keys are 'user_{user_id}_{YYYYMMDD}' so date-range filtering
        is done on the key name itself — no need to read every file.
        """
        start, end = _parse_period(period)
        start_date = start.strftime("%Y%m%d")
        end_date = end.strftime("%Y%m%d")
        prefix = f"user_{user_id}_"

        sessions = await self._conv_store.get_all_sessions(user_id)
        in_range = [
            sk for sk in sessions
            if sk.startswith(prefix) and start_date <= sk[len(prefix):] <= end_date
        ]

        total_user = 0
        total_assistant = 0
        active_days: set[str] = set()
        model_counts: dict[str, int] = {}

        for session_key in in_range:
            turns = await self._conv_store.get_recent_turns(user_id, session_key, limit=5000)
            for turn in turns:
                if turn.role == "user":
                    total_user += 1
                elif turn.role == "assistant":
                    if turn.content.startswith("[COMPACTED"):
                        continue
                    total_assistant += 1
                    model = turn.model_used or "unknown"
                    model_counts[model] = model_counts.get(model, 0) + 1

            # Derive day from the session key suffix (YYYYMMDD)
            suffix = session_key[len(prefix):]
            if len(suffix) == 8 and suffix.isdigit():
                day_str = f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:]}"
                active_days.add(day_str)

        period_days = max(1, (end - start).days)
        avg_per_day = round(total_user / period_days, 1) if total_user else 0.0

        return {
            "period": period,
            "period_label": _period_label(period),
            "total_messages": total_user + total_assistant,
            "user_messages": total_user,
            "assistant_messages": total_assistant,
            "active_days": len(active_days),
            "period_days": period_days,
            "avg_messages_per_day": avg_per_day,
            "models_used": model_counts,
        }

    async def get_active_goals_with_age(self, user_id: int) -> list[dict[str, Any]]:
        """Return active goals annotated with human-readable age strings."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, title, description, created_at, updated_at
                FROM goals WHERE user_id=? AND status='active'
                ORDER BY created_at ASC
                """,
                (user_id,),
            )
        now = datetime.now(timezone.utc)
        result = []
        for row in rows:
            d = dict(row)
            for field in ("created_at", "updated_at"):
                ts_str = d.get(field)
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        days = (now - ts).days
                        d[f"{field}_age"] = (
                            "today" if days == 0
                            else "yesterday" if days == 1
                            else f"{days} days ago"
                        )
                        d[f"{field}_days"] = days
                    except ValueError:
                        d[f"{field}_age"] = "unknown"
                        d[f"{field}_days"] = 0
            result.append(d)
        return result

    async def get_completed_goals_since(
        self, user_id: int, since: datetime
    ) -> list[dict[str, Any]]:
        """Return goals completed since the given datetime, newest first."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, title, description, updated_at
                FROM goals
                WHERE user_id=? AND status='completed' AND updated_at >= ?
                ORDER BY updated_at DESC
                """,
                (user_id, since.isoformat()),
            )
        return [dict(row) for row in rows]

    def format_stats_message(self, stats: dict[str, Any]) -> str:
        """Format a stats dict into a Telegram-ready Markdown message."""
        label = stats["period_label"]
        user_msgs = stats["user_messages"]
        asst_msgs = stats["assistant_messages"]
        total = stats["total_messages"]
        active = stats["active_days"]
        period_days = stats["period_days"]
        avg = stats["avg_messages_per_day"]
        models = stats["models_used"]

        lines = [f"📊 *Your stats for {label}*\n"]
        lines.append(f"💬 *Messages:* {total} ({user_msgs} from you, {asst_msgs} from me)")
        lines.append(f"📅 *Active days:* {active} / {period_days}")
        lines.append(f"📈 *Average:* {avg} messages/day from you")

        display_models = {
            k: v for k, v in models.items()
            if k not in ("unknown", "compact", "")
        }
        if display_models:
            model_lines = "\n".join(
                f"  • {k}: {v}"
                for k, v in sorted(display_models.items(), key=lambda x: -x[1])
            )
            lines.append(f"🤖 *Models used:*\n{model_lines}")

        if total == 0:
            lines.append("\n_No conversations recorded in this period._")
        else:
            lines.append(
                f"\n_You chatted with me on {active} of the last {period_days} days._"
            )

        return "\n".join(lines)

    def format_goal_status_message(
        self,
        active_goals: list[dict[str, Any]],
        completed_goals: list[dict[str, Any]],
    ) -> str:
        """Format the goal status dashboard into a Telegram Markdown message."""
        lines = ["🎯 *Goal Status Dashboard*\n"]
        stale_count = 0

        if active_goals:
            lines.append(f"📋 *Active goals ({len(active_goals)}):*")
            for i, g in enumerate(active_goals, 1):
                title = g.get("title", "Untitled")
                created_age = g.get("created_at_age", "unknown")
                updated_age = g.get("updated_at_age", "unknown")
                updated_days = g.get("updated_at_days", 0)
                stale_marker = " ⚠️" if updated_days >= _STALE_DAYS else ""
                if updated_days >= _STALE_DAYS:
                    stale_count += 1
                lines.append(
                    f"  {i}. *{title}*\n"
                    f"     Created {created_age} · Last update {updated_age}{stale_marker}"
                )
        else:
            lines.append("_No active goals. Tell me what you're working on!_")

        if completed_goals:
            lines.append(f"\n✅ *Completed last 30 days ({len(completed_goals)}):*")
            for g in completed_goals[:10]:
                title = g.get("title", "Untitled")
                ts_str = g.get("updated_at", "")
                date_str = ""
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        date_str = f" ({ts.strftime('%b')} {ts.day})"
                    except ValueError:
                        pass
                lines.append(f"  • {title}{date_str}")

        if stale_count:
            noun = "goal" if stale_count == 1 else "goals"
            lines.append(
                f"\n💡 _{stale_count} {noun} haven't been updated in 3+ days. Still on track?_"
            )

        return "\n".join(lines)

    async def generate_retrospective(
        self,
        user_id: int,
        period: str,
        claude_client: "ClaudeClient",
    ) -> str:
        """Generate a monthly retrospective using Claude."""
        from ..config import settings

        start, _end = _parse_period(period)
        stats = await self.get_stats(user_id, period)
        active_goals = await self.get_active_goals_with_age(user_id)
        completed_goals = await self.get_completed_goals_since(user_id, start)

        month_name = start.strftime("%B %Y") if period in ("month", "30d") else stats["period_label"]

        stats_block = (
            f"Period: {stats['period_label']}\n"
            f"Messages from user: {stats['user_messages']}\n"
            f"Active days: {stats['active_days']} / {stats['period_days']}\n"
        )

        if active_goals:
            active_lines = [
                f"- {g['title']} (active for {g.get('created_at_age', 'unknown')}, "
                f"last update {g.get('updated_at_age', 'unknown')})"
                for g in active_goals[:10]
            ]
            active_block = "Active goals:\n" + "\n".join(active_lines)
        else:
            active_block = "Active goals: none"

        if completed_goals:
            completed_lines = [f"- {g['title']}" for g in completed_goals[:10]]
            completed_block = "Completed this period:\n" + "\n".join(completed_lines)
        else:
            completed_block = "Completed this period: none"

        prompt = (
            f"Write a personal retrospective for Dale for {month_name}.\n\n"
            f"Data:\n{stats_block}\n{active_block}\n\n{completed_block}\n\n"
            "Format as a Telegram message with Markdown. Include:\n"
            "1. A brief headline (1 sentence — celebrate a win or acknowledge a quiet period)\n"
            "2. Highlights / wins (from completed goals, or conversation activity)\n"
            "3. Still in progress (active goals, gently call out any stale ones)\n"
            "4. Suggested focus for next period (1–3 items based on active goals)\n"
            "5. One encouraging closing sentence\n\n"
            "Tone: warm, honest, ADHD-friendly. No corporate jargon. Max 300 words."
        )

        try:
            response = await claude_client.complete(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are Dale's personal AI assistant writing a monthly retrospective. "
                    "Be warm, direct, and encouraging."
                ),
                model=settings.model_complex,
                max_tokens=800,
            )
            header = f"📅 *Monthly Retrospective — {month_name}*\n\n"
            return header + (response if isinstance(response, str) else str(response))
        except Exception as e:
            logger.error("Failed to generate retrospective: %s", e)
            return (
                f"📅 *Monthly Retrospective — {month_name}*\n\n"
                "_(Claude unavailable — stats summary)_\n\n"
                + self.format_stats_message(stats)
            )
