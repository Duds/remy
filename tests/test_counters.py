"""Tests for remy.memory.counters — CounterStore."""

import pytest
import pytest_asyncio

from remy.memory.database import DatabaseManager
from remy.memory.counters import CounterStore, INJECT_COUNTER_NAMES


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh DB with counters table."""
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    await manager.init()
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def store(db):
    """CounterStore with user USER_ID present (counters FK references users)."""
    await db.upsert_user(USER_ID, username="test", first_name="Test", last_name="User")
    return CounterStore(db)


USER_ID = 99


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    """get() for a counter that does not exist returns None."""
    assert await store.get(USER_ID, "sobriety_streak") is None


@pytest.mark.asyncio
async def test_set_and_get(store):
    """set() then get() returns value, unit, updated_at."""
    await store.set(USER_ID, "sobriety_streak", 14, unit="days")
    row = await store.get(USER_ID, "sobriety_streak")
    assert row is not None
    assert row["value"] == 14
    assert row["unit"] == "days"
    assert "updated_at" in row


@pytest.mark.asyncio
async def test_set_overwrites(store):
    """set() overwrites existing value."""
    await store.set(USER_ID, "sobriety_streak", 5)
    await store.set(USER_ID, "sobriety_streak", 10)
    row = await store.get(USER_ID, "sobriety_streak")
    assert row["value"] == 10


@pytest.mark.asyncio
async def test_set_negative_raises(store):
    """set() with negative value raises ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        await store.set(USER_ID, "x", -1)


@pytest.mark.asyncio
async def test_increment_creates_at_zero(store):
    """increment() on missing counter creates at 0 + by, returns new value."""
    val = await store.increment(USER_ID, "sobriety_streak", by=1)
    assert val == 1
    assert (await store.get(USER_ID, "sobriety_streak"))["value"] == 1


@pytest.mark.asyncio
async def test_increment_adds(store):
    """increment() adds by and returns new value."""
    await store.set(USER_ID, "sobriety_streak", 5)
    val = await store.increment(USER_ID, "sobriety_streak", by=3)
    assert val == 8


@pytest.mark.asyncio
async def test_reset_sets_zero(store):
    """reset() sets counter to 0."""
    await store.set(USER_ID, "sobriety_streak", 20)
    await store.reset(USER_ID, "sobriety_streak")
    row = await store.get(USER_ID, "sobriety_streak")
    assert row["value"] == 0


@pytest.mark.asyncio
async def test_get_all_for_inject_empty(store):
    """get_all_for_inject() returns [] when no counters set."""
    assert await store.get_all_for_inject(USER_ID) == []


@pytest.mark.asyncio
async def test_get_all_for_inject_only_inject_names(store):
    """get_all_for_inject() returns only counters in INJECT_COUNTER_NAMES with value > 0."""
    await store.set(USER_ID, "sobriety_streak", 7, unit="days")
    result = await store.get_all_for_inject(USER_ID)
    assert len(result) == 1
    assert result[0]["name"] == "sobriety_streak"
    assert result[0]["value"] == 7
    assert result[0]["unit"] == "days"


@pytest.mark.asyncio
async def test_get_all_for_inject_skips_zero(store):
    """get_all_for_inject() skips counters with value 0."""
    await store.set(USER_ID, "sobriety_streak", 0)
    assert await store.get_all_for_inject(USER_ID) == []


@pytest.mark.asyncio
async def test_inject_counter_names_contains_sobriety():
    """INJECT_COUNTER_NAMES includes sobriety_streak."""
    assert "sobriety_streak" in INJECT_COUNTER_NAMES


@pytest.mark.asyncio
async def test_increment_daily_if_new_day_increments_when_not_today(store, db):
    """increment_daily_if_new_day increments when last_increment_date is before today or null."""
    from zoneinfo import ZoneInfo

    await store.set(USER_ID, "sobriety_streak", 3)
    # Backdate last_increment_date so the daily job sees a new day
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE counters SET last_increment_date = '2020-01-01' WHERE user_id = ? AND name = ?",
            (USER_ID, "sobriety_streak"),
        )
        await conn.commit()
    tz = ZoneInfo("Australia/Sydney")
    did = await store.increment_daily_if_new_day(USER_ID, "sobriety_streak", tz=tz)
    assert did is True
    row = await store.get(USER_ID, "sobriety_streak")
    assert row["value"] == 4


@pytest.mark.asyncio
async def test_increment_daily_if_new_day_no_op_when_already_today(store):
    """increment_daily_if_new_day does not increment twice the same day (set() sets last_increment_date)."""
    from zoneinfo import ZoneInfo

    await store.set(USER_ID, "sobriety_streak", 5)
    tz = ZoneInfo("Australia/Sydney")
    did = await store.increment_daily_if_new_day(USER_ID, "sobriety_streak", tz=tz)
    # set() already set last_increment_date to today, so no increment
    assert did is False
    row = await store.get(USER_ID, "sobriety_streak")
    assert row["value"] == 5


@pytest.mark.asyncio
async def test_increment_daily_if_new_day_no_op_when_zero(store):
    """increment_daily_if_new_day does not increment when value is 0."""
    from zoneinfo import ZoneInfo

    await store.reset(USER_ID, "sobriety_streak")
    tz = ZoneInfo("Australia/Sydney")
    did = await store.increment_daily_if_new_day(USER_ID, "sobriety_streak", tz=tz)
    assert did is False
    row = await store.get(USER_ID, "sobriety_streak")
    assert row["value"] == 0
