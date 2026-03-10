"""Tests for remy.memory.automations — AutomationStore (reminder deep links: get_for_user)."""

import pytest
import pytest_asyncio
from remy.memory.database import DatabaseManager
from remy.memory.automations import AutomationStore


@pytest_asyncio.fixture
async def db(tmp_path):
    manager = DatabaseManager(db_path=str(tmp_path / "auto_test.db"))
    await manager.init()
    await manager.upsert_user(100)
    await manager.upsert_user(200)
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def automation_store(db):
    return AutomationStore(db)


@pytest.mark.asyncio
async def test_get_for_user_returns_row_when_owner(automation_store):
    """US-reminder-deep-links: get_for_user returns automation when user_id matches."""
    rid = await automation_store.add(
        user_id=100, label="Standup", cron="0 9 * * *", fire_at=None
    )
    row = await automation_store.get_for_user(100, rid)
    assert row is not None
    assert row["id"] == rid
    assert row["user_id"] == 100
    assert row["label"] == "Standup"


@pytest.mark.asyncio
async def test_get_for_user_returns_none_when_wrong_user(automation_store):
    """get_for_user returns None when automation belongs to another user."""
    rid = await automation_store.add(
        user_id=100, label="Private", cron="0 8 * * *", fire_at=None
    )
    row = await automation_store.get_for_user(200, rid)
    assert row is None


@pytest.mark.asyncio
async def test_get_for_user_returns_none_when_not_found(automation_store):
    """get_for_user returns None when automation_id does not exist."""
    row = await automation_store.get_for_user(100, 99999)
    assert row is None
