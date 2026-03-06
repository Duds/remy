"""Tests for heartbeat job: quiet hours, run_heartbeat_job, heartbeat_log (SAD v7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.scheduler.heartbeat import _in_quiet_hours, run_heartbeat_job


def test_in_quiet_hours_when_inside_interval():
    """When hour is between quiet_start and midnight or before quiet_end, returns True."""
    mock_now = MagicMock()
    mock_now.hour = 23
    with patch("remy.scheduler.heartbeat.datetime") as mdt:
        mdt.now.return_value = mock_now
        with patch("remy.scheduler.heartbeat.settings") as s:
            s.heartbeat_quiet_start = 22
            s.heartbeat_quiet_end = 7
            s.scheduler_timezone = "Australia/Sydney"
            assert _in_quiet_hours() is True


def test_in_quiet_hours_when_outside_interval():
    """When hour is outside 22--07, returns False."""
    mock_now = MagicMock()
    mock_now.hour = 12
    with patch("remy.scheduler.heartbeat.datetime") as mdt:
        mdt.now.return_value = mock_now
        with patch("remy.scheduler.heartbeat.settings") as s:
            s.heartbeat_quiet_start = 22
            s.heartbeat_quiet_end = 7
            s.scheduler_timezone = "Australia/Sydney"
            assert _in_quiet_hours() is False


@pytest.mark.asyncio
async def test_run_heartbeat_job_skips_when_no_chat_or_user(tmp_path):
    """When get_primary_chat_id or get_primary_user_id returns None, job exits without running handler."""
    db = MagicMock()
    db.get_connection = AsyncMock()
    handler = MagicMock()
    handler.run = AsyncMock()
    await run_heartbeat_job(
        handler=handler,
        db=db,
        get_primary_chat_id=lambda: None,
        get_primary_user_id=lambda: 1,
    )
    handler.run.assert_not_called()


@pytest.mark.asyncio
async def test_run_heartbeat_job_writes_heartbeat_log(tmp_path):
    """When chat_id and user_id are set and not quiet hours, handler runs and log is written."""
    with patch("remy.scheduler.heartbeat._in_quiet_hours", return_value=False):
        with patch("remy.scheduler.heartbeat.load_heartbeat_config", return_value="# Config"):
            from remy.memory.database import DatabaseManager

            db_path = str(tmp_path / "remy.db")
            db = DatabaseManager(db_path=db_path)
            await db.init()

            result_mock = MagicMock()
            result_mock.outcome = "HEARTBEAT_OK"
            result_mock.items_checked = {"goals": "None"}
            result_mock.items_surfaced = {}
            result_mock.model = ""
            result_mock.tokens_used = 0
            result_mock.duration_ms = 10

            handler = MagicMock()
            handler.run = AsyncMock(return_value=result_mock)

            await run_heartbeat_job(
                handler=handler,
                db=db,
                get_primary_chat_id=lambda: 12345,
                get_primary_user_id=lambda: 1,
            )

            handler.run.assert_called_once()
            async with db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT outcome, duration_ms FROM heartbeat_log ORDER BY id DESC LIMIT 1"
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == "HEARTBEAT_OK"
