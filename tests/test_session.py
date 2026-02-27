"""Tests for remy/bot/session.py"""

import asyncio
import pytest
from remy.bot.session import SessionManager, validate_session_key


def test_validate_session_key_valid():
    assert validate_session_key("user_123_20260225") is True
    assert validate_session_key("user-1-proactive") is True


def test_validate_session_key_invalid():
    assert validate_session_key("") is False
    assert validate_session_key("../etc/passwd") is False
    assert validate_session_key("a" * 65) is False
    assert validate_session_key("user 1 date") is False


def test_get_session_key_format():
    key = SessionManager.get_session_key(42)
    assert key.startswith("user_42_")
    assert len(key) == len("user_42_20260225")  # same length


def test_lock_is_per_user():
    sm = SessionManager()
    lock_a = sm.get_lock(1)
    lock_b = sm.get_lock(2)
    lock_a2 = sm.get_lock(1)
    assert lock_a is lock_a2
    assert lock_a is not lock_b


def test_cancel_lifecycle():
    sm = SessionManager()
    assert not sm.is_cancelled(1)
    sm.request_cancel(1)
    assert sm.is_cancelled(1)
    sm.clear_cancel(1)
    assert not sm.is_cancelled(1)


@pytest.mark.asyncio
async def test_lock_serialises_access():
    sm = SessionManager()
    results = []

    async def task(n):
        async with sm.get_lock(1):
            results.append(f"start_{n}")
            await asyncio.sleep(0.01)
            results.append(f"end_{n}")

    await asyncio.gather(task(1), task(2))
    # Tasks should interleave at the lock boundary, not within
    assert results.index("end_1") < results.index("start_2") or \
           results.index("end_2") < results.index("start_1")
