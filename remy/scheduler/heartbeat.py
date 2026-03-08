"""Evaluative heartbeat job — schedule, silence guard, hooks, log.

SAD v7: single job runs every 30 min (configurable), skips quiet hours,
emits HEARTBEAT_START/END, runs HeartbeatHandler, writes heartbeat_log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import settings
from ..hooks import HookEvents, hook_manager
from .heartbeat_config import load_heartbeat_config

logger = logging.getLogger(__name__)


async def _get_already_surfaced_today(db, tz: ZoneInfo | timezone) -> str:
    """Return a short summary of what the heartbeat already delivered today (user's timezone)."""
    now = datetime.now(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    today_end_utc = (
        (today_start.replace(hour=23, minute=59, second=59) + timedelta(seconds=1))
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S")
    )

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT fired_at, items_surfaced FROM heartbeat_log
            WHERE outcome = 'delivered' AND fired_at >= ? AND fired_at < ?
            ORDER BY fired_at ASC
            """,
            (today_start_utc, today_end_utc),
        )
        rows = await cursor.fetchall()
    if not rows:
        return "None yet today."
    lines = []
    for row in rows:
        fired_at_str = row[0] if row[0] else ""
        items = row[1]
        try:
            if items:
                d = json.loads(items)
                preview = (d.get("message") or "")[:60]
            else:
                preview = "(delivered)"
        except Exception:
            preview = "(delivered)"
        if fired_at_str:
            try:
                utc_dt = datetime.fromisoformat(fired_at_str.replace("Z", "+00:00"))
                local_dt = utc_dt.astimezone(tz)
                time_part = local_dt.strftime("%H:%M")
            except Exception:
                time_part = fired_at_str[:16]
        else:
            time_part = "?"
        lines.append(f"{time_part} — {preview}")
    return "\n".join(lines)


def _in_quiet_hours() -> bool:
    """True if current time is in heartbeat quiet hours (no evaluation)."""
    tz: ZoneInfo | timezone
    try:
        tz = ZoneInfo(settings.scheduler_timezone)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    hour = now.hour
    start = settings.heartbeat_quiet_start
    end = settings.heartbeat_quiet_end
    if start > end:  # e.g. 22–07
        return hour >= start or hour < end
    return start <= hour < end


async def run_heartbeat_job(
    handler,  # HeartbeatHandler
    db,  # DatabaseManager
    get_primary_chat_id,  # callable[[], int | None]
    get_primary_user_id,  # callable[[], int | None]
) -> None:
    """Run one heartbeat evaluation: silence guard, gather, evaluate, log."""
    if _in_quiet_hours():
        logger.debug("Heartbeat skipped — quiet hours")
        return

    chat_id = (
        get_primary_chat_id() if callable(get_primary_chat_id) else get_primary_chat_id
    )
    user_id = (
        get_primary_user_id() if callable(get_primary_user_id) else get_primary_user_id
    )
    if chat_id is None or user_id is None:
        logger.debug("Heartbeat skipped — no primary chat or user")
        return

    await hook_manager.emit(
        HookEvents.HEARTBEAT_START, {"chat_id": chat_id, "user_id": user_id}
    )

    config_text = load_heartbeat_config()

    # Current time in user's timezone so the model can apply Daily Orientation / Wellbeing windows
    tz: ZoneInfo | timezone
    try:
        tz = ZoneInfo(settings.scheduler_timezone)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    current_local_time = now.strftime("%Y-%m-%d %H:%M %Z (day of week: %A)")

    # What we've already delivered today (so model can enforce "at most once per day" etc.)
    already_surfaced_today = await _get_already_surfaced_today(db, tz)

    # Agent Tasks: query unsurfaced done/failed/stalled tasks for heartbeat context
    agent_tasks_context: str | None = None
    unsurfaced_task_ids: list[str] = []
    try:
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT task_id, worker_type, status, synthesis, error
                  FROM agent_tasks
                 WHERE status IN ('failed', 'stalled', 'done')
                   AND surfaced_to_remy = 0
                 ORDER BY created_at ASC
                 LIMIT 20
                """,
            )
            task_rows = await cursor.fetchall()
        if task_rows:
            lines: list[str] = []
            for row in task_rows:
                tid, wtype, status, synthesis, error = row
                unsurfaced_task_ids.append(tid)
                if synthesis:
                    try:
                        syn = json.loads(synthesis)
                        summary = syn.get("summary", "")[:200]
                    except Exception:
                        summary = synthesis[:200]
                else:
                    summary = error[:200] if error else "(no detail)"
                lines.append(
                    f"• [{status}] {wtype} task {tid[:8]}: {summary}"
                )
            agent_tasks_context = (
                "Agent tasks requiring attention:\n" + "\n".join(lines)
            )
    except Exception as _at_err:
        logger.warning("Could not query agent_tasks for heartbeat: %s", _at_err)

    result = await handler.run(
        user_id=user_id,
        chat_id=chat_id,
        config_text=config_text,
        current_local_time=current_local_time,
        already_surfaced_today=already_surfaced_today,
        agent_tasks_context=agent_tasks_context,
    )

    # Mark queried tasks as surfaced (they were included in the evaluation context)
    if unsurfaced_task_ids:
        try:
            async with db.get_connection() as conn:
                placeholders = ",".join("?" * len(unsurfaced_task_ids))
                await conn.execute(
                    f"UPDATE agent_tasks SET surfaced_to_remy=1"  # noqa: S608
                    f" WHERE task_id IN ({placeholders})",
                    unsurfaced_task_ids,
                )
                await conn.commit()
        except Exception as _mark_err:
            logger.warning(
                "Could not mark agent_tasks as surfaced: %s", _mark_err
            )

    fired_at = datetime.now(timezone.utc).isoformat()
    try:
        items_checked_json = (
            json.dumps(result.items_checked) if result.items_checked else None
        )
        items_surfaced_json = (
            json.dumps(result.items_surfaced) if result.items_surfaced else None
        )
    except (TypeError, ValueError):
        items_checked_json = None
        items_surfaced_json = None

    async with db.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO heartbeat_log
                (fired_at, outcome, items_checked, items_surfaced, model, tokens_used, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fired_at,
                result.outcome,
                items_checked_json,
                items_surfaced_json,
                result.model or None,
                result.tokens_used or None,
                result.duration_ms or None,
            ),
        )
        await conn.commit()

    await hook_manager.emit(
        HookEvents.HEARTBEAT_END,
        {
            "outcome": result.outcome,
            "duration_ms": result.duration_ms,
            "chat_id": chat_id,
        },
    )

    if result.outcome == "HEARTBEAT_OK":
        logger.debug("Heartbeat: HEARTBEAT_OK (nothing to surface)")
    else:
        logger.info(
            "Heartbeat: delivered to chat %d (%d ms)", chat_id, result.duration_ms
        )
