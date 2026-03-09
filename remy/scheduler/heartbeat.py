"""Evaluative heartbeat job — schedule, silence guard, hooks, log.

SAD v7: single job runs every 30 min (configurable), skips quiet hours,
emits HEARTBEAT_START/END, runs HeartbeatHandler, writes heartbeat_log.

Paperclip additions:
- Budget enforcement: warns at budget_warning_pct, pauses non-critical LLM calls at monthly_budget_aud.
- Auto-requeue: relay tasks stuck in_progress for >30 min are reverted to pending.
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


# Module-level flag set by check_budget(); guards non-critical LLM calls.
budget_exhausted: bool = False

# Track the date we last sent the budget warning to avoid spamming.
_budget_warning_sent_date: str = ""


async def check_budget(db, enqueue_message=None) -> dict:
    """Compute month-to-date Anthropic spend and enforce budget limits.

    Costs are approximated in USD from token counts, then compared against the
    AUD cap (monthly_budget_aud). A fixed exchange rate of 1 USD = 1.55 AUD is
    used for the conversion; adjust AUD_PER_USD below if rates shift materially.

    Returns a dict: {"month_aud": float, "budget_aud": float, "pct": float, "exhausted": bool}.
    When enqueue_message is provided it is called with a warning string when thresholds are crossed.
    """
    global budget_exhausted, _budget_warning_sent_date

    # Approximate USD → AUD conversion (Anthropic bills in USD).
    AUD_PER_USD = 1.55

    limit_aud = settings.monthly_budget_aud
    if limit_aud <= 0:
        return {"month_aud": 0.0, "budget_aud": 0.0, "pct": 0.0, "exhausted": False}

    # Sum Anthropic tokens for the current calendar month (UTC).
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01T00:00:00")
    try:
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT COALESCE(SUM(input_tokens), 0)  AS inp,
                       COALESCE(SUM(output_tokens), 0) AS out
                FROM api_calls
                WHERE provider = 'anthropic'
                  AND timestamp >= ?
                """,
                (month_start,),
            )
            row = await cursor.fetchone()
    except Exception as e:
        logger.warning("Budget check failed (non-fatal): %s", e)
        return {"month_aud": 0.0, "budget_aud": limit_aud, "pct": 0.0, "exhausted": False}

    inp_tokens = int(row[0]) if row else 0
    out_tokens = int(row[1]) if row else 0
    # Approximate pricing: Sonnet input $3/M, output $15/M (USD), converted to AUD
    month_usd = (inp_tokens * 3 + out_tokens * 15) / 1_000_000
    month_aud = month_usd * AUD_PER_USD
    pct = month_aud / limit_aud if limit_aud else 0.0

    if pct >= 1.0:
        budget_exhausted = True
        if enqueue_message:
            msg = f"⛔ Monthly LLM budget exhausted (A${month_aud:.2f}/A${limit_aud:.2f}). Non-critical calls paused."
            try:
                enqueue_message(msg)
            except Exception:
                pass
        logger.warning("Monthly budget exhausted: A$%.2f / A$%.2f", month_aud, limit_aud)
    elif pct >= settings.budget_warning_pct:
        budget_exhausted = False
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != _budget_warning_sent_date:
            _budget_warning_sent_date = today
            if enqueue_message:
                msg = f"⚠️ LLM budget at {pct*100:.0f}% (A${month_aud:.2f}/A${limit_aud:.2f})."
                try:
                    enqueue_message(msg)
                except Exception:
                    pass
            logger.info("Budget warning: A$%.2f / A$%.2f (%.0f%%)", month_aud, limit_aud, pct * 100)
    else:
        budget_exhausted = False

    return {
        "month_aud": month_aud,
        "budget_aud": limit_aud,
        "pct": pct,
        "exhausted": budget_exhausted,
    }


async def requeue_stuck_relay_tasks(db) -> int:
    """Revert relay tasks that have been in_progress for >30 minutes back to pending.

    Returns the number of tasks requeued.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    try:
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id FROM tasks
                WHERE to_agent = 'remy'
                  AND status = 'in_progress'
                  AND updated_at < ?
                """,
                (cutoff,),
            )
            stuck = [row[0] for row in await cursor.fetchall()]

        if not stuck:
            return 0

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        async with db.get_connection() as conn:
            for task_id in stuck:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'pending',
                        notes = COALESCE(notes || ' | ', '') || 'Auto-requeued: timed out after 30 minutes (' || ? || ')',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, task_id),
                )
            await conn.commit()

        logger.info("Auto-requeued %d stuck relay task(s)", len(stuck))
        return len(stuck)
    except Exception as e:
        logger.warning("requeue_stuck_relay_tasks failed (non-fatal): %s", e)
        return 0


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
    enqueue_message=None,  # optional callable(str) to send a Telegram message
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

    # Budget enforcement (paperclip §5): check spend and surface warnings
    await check_budget(db, enqueue_message=enqueue_message)

    # Auto-requeue stuck relay tasks (paperclip §7)
    await requeue_stuck_relay_tasks(db)

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
