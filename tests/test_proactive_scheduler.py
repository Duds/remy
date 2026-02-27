"""
Tests for remy/scheduler/proactive.py.

APScheduler is NOT triggered in tests — we call the job coroutines directly.
The Telegram bot.send_message is mocked.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from remy.memory.database import DatabaseManager
from remy.memory.embeddings import EmbeddingStore
from remy.memory.goals import GoalStore
from remy.models import Goal
from remy.scheduler.proactive import (
    ProactiveScheduler,
    _parse_cron,
    _read_primary_chat_id,
    _STALE_GOAL_DAYS,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def db(tmp_path):
    manager = DatabaseManager(db_path=str(tmp_path / "sched_test.db"))
    await manager.init()
    await manager.upsert_user(1)
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def goal_store(db):
    embeddings = EmbeddingStore(db)
    return GoalStore(db, embeddings)


def make_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


def make_scheduler(bot, goal_store):
    return ProactiveScheduler(bot, goal_store)


# --------------------------------------------------------------------------- #
# _parse_cron tests                                                            #
# --------------------------------------------------------------------------- #

def test_parse_cron_valid():
    from apscheduler.triggers.cron import CronTrigger
    trigger = _parse_cron("0 7 * * *")
    assert isinstance(trigger, CronTrigger)


def test_parse_cron_invalid_raises():
    with pytest.raises(ValueError, match="Invalid cron"):
        _parse_cron("0 7 * *")  # only 4 fields


# --------------------------------------------------------------------------- #
# _read_primary_chat_id tests                                                  #
# --------------------------------------------------------------------------- #

def test_read_primary_chat_id_returns_none_when_missing(tmp_path):
    with patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.primary_chat_file = str(tmp_path / "nonexistent.txt")
        result = _read_primary_chat_id()
    assert result is None


def test_read_primary_chat_id_returns_id(tmp_path):
    chat_file = tmp_path / "primary_chat_id.txt"
    chat_file.write_text("987654321")
    with patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.primary_chat_file = str(chat_file)
        result = _read_primary_chat_id()
    assert result == 987654321


def test_read_primary_chat_id_returns_none_for_empty_file(tmp_path):
    chat_file = tmp_path / "primary_chat_id.txt"
    chat_file.write_text("")
    with patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.primary_chat_file = str(chat_file)
        result = _read_primary_chat_id()
    assert result is None


def test_read_primary_chat_id_returns_none_for_invalid_content(tmp_path):
    chat_file = tmp_path / "primary_chat_id.txt"
    chat_file.write_text("not-a-number")
    with patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.primary_chat_file = str(chat_file)
        result = _read_primary_chat_id()
    assert result is None


# --------------------------------------------------------------------------- #
# Morning briefing tests                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_morning_briefing_skipped_when_no_chat_id(db, goal_store, tmp_path):
    """No send if primary_chat_id not set."""
    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=None):
        await sched._morning_briefing()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_morning_briefing_skipped_when_no_allowed_users(db, goal_store):
    """No send if allowed users list is empty."""
    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=12345), \
         patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.telegram_allowed_users = []
        mock_settings.briefing_cron = "0 7 * * *"
        mock_settings.checkin_cron = "0 19 * * *"
        mock_settings.scheduler_timezone = "Australia/Sydney"
        await sched._morning_briefing()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_morning_briefing_sends_with_goals(db, goal_store):
    """Briefing should include active goal titles."""
    await goal_store.upsert(1, [Goal(title="Launch remy", description="My AI agent")])

    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=12345), \
         patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.telegram_allowed_users = [1]
        mock_settings.scheduler_timezone = "Australia/Sydney"
        await sched._morning_briefing()

    bot.send_message.assert_called_once()
    call_kwargs = bot.send_message.call_args
    text = call_kwargs.kwargs.get("text") or call_kwargs.args[1] if call_kwargs.args else ""
    if not text:
        text = call_kwargs.kwargs.get("text", "")
    assert "Launch remy" in text
    assert call_kwargs.kwargs.get("chat_id") == 12345 or (
        call_kwargs.args and call_kwargs.args[0] == 12345
    )


@pytest.mark.asyncio
async def test_morning_briefing_no_goals_message(db, goal_store):
    """With no goals, briefing should mention 'no active goals'."""
    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=99), \
         patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.telegram_allowed_users = [1]
        mock_settings.scheduler_timezone = "Australia/Sydney"
        await sched._morning_briefing()

    bot.send_message.assert_called_once()
    text = bot.send_message.call_args.kwargs.get("text", "")
    assert "no active goals" in text.lower()


@pytest.mark.asyncio
async def test_morning_briefing_swallows_send_error(db, goal_store):
    """A failed Telegram send should not crash the scheduler."""
    bot = make_bot()
    bot.send_message = AsyncMock(side_effect=RuntimeError("Telegram API down"))
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=99), \
         patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.telegram_allowed_users = [1]
        mock_settings.scheduler_timezone = "Australia/Sydney"
        # Should not raise
        await sched._morning_briefing()


# --------------------------------------------------------------------------- #
# Evening check-in tests                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_evening_checkin_skipped_when_no_chat_id(db, goal_store):
    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=None):
        await sched._evening_checkin()
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_evening_checkin_skipped_when_no_stale_goals(db, goal_store):
    """Fresh goals (updated recently) should NOT trigger a check-in."""
    await goal_store.upsert(1, [Goal(title="Recent goal")])

    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=12345), \
         patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.telegram_allowed_users = [1]
        # Don't patch stale detection — goal was just inserted, so not stale
        await sched._evening_checkin()

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_evening_checkin_sends_for_stale_goals(db, goal_store):
    """Goals older than _STALE_GOAL_DAYS should trigger a check-in message."""
    await goal_store.upsert(1, [Goal(title="Old goal")])

    # Manually backdate the goal's created_at to make it stale
    stale_ts = (
        datetime.now(timezone.utc) - timedelta(days=_STALE_GOAL_DAYS + 1)
    ).strftime("%Y-%m-%d %H:%M:%S")
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE goals SET created_at=?, updated_at=? WHERE title='Old goal'",
            (stale_ts, stale_ts),
        )
        await conn.commit()

    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive._read_primary_chat_id", return_value=12345), \
         patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.telegram_allowed_users = [1]
        await sched._evening_checkin()

    bot.send_message.assert_called_once()
    text = bot.send_message.call_args.kwargs.get("text", "")
    assert "Old goal" in text


# --------------------------------------------------------------------------- #
# Scheduler start / stop                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_scheduler_start_and_stop(db, goal_store):
    """start() and stop() should not raise (requires running event loop)."""
    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    sched.start()
    assert sched._scheduler.running
    # stop() calls shutdown(wait=False); the scheduler may still report running
    # briefly in the same tick — just verify it doesn't raise
    sched.stop()  # should not raise


@pytest.mark.asyncio
async def test_scheduler_start_with_bad_cron_does_not_crash(db, goal_store):
    """Invalid cron should log an error and not start the scheduler."""
    bot = make_bot()
    sched = make_scheduler(bot, goal_store)
    with patch("remy.scheduler.proactive.settings") as mock_settings:
        mock_settings.briefing_cron = "bad cron string"
        mock_settings.checkin_cron = "0 19 * * *"
        mock_settings.scheduler_timezone = "Australia/Sydney"
        sched.start()
    # Scheduler should NOT be running
    assert not sched._scheduler.running
