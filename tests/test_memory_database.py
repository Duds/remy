"""Tests for drbot/memory/database.py — schema init, WAL mode, user upsert."""

import pytest
import pytest_asyncio

from drbot.memory.database import DatabaseManager


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh in-memory-style DB per test (temp file)."""
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    await manager.init()
    yield manager
    await manager.close()


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    """All expected tables should exist after init."""
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {r["name"] for r in rows}

    assert "users" in names
    assert "facts" in names
    assert "goals" in names
    assert "embeddings" in names
    assert "conversations" in names
    assert "photos" in names


@pytest.mark.asyncio
async def test_init_creates_fts_virtual_tables(db):
    """FTS5 virtual tables must exist."""
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts'"
        )
        names = {r["name"] for r in rows}

    assert "facts_fts" in names
    assert "goals_fts" in names


@pytest.mark.asyncio
async def test_wal_mode_enabled(db):
    """Journal mode should be WAL after init."""
    async with db.get_connection() as conn:
        row = (await conn.execute_fetchall("PRAGMA journal_mode"))[0]
    assert row[0] == "wal"


@pytest.mark.asyncio
async def test_foreign_keys_enabled(db):
    """Foreign keys must be enforced."""
    async with db.get_connection() as conn:
        row = (await conn.execute_fetchall("PRAGMA foreign_keys"))[0]
    assert row[0] == 1


@pytest.mark.asyncio
async def test_upsert_user_creates_row(db):
    """upsert_user should insert a new user row."""
    await db.upsert_user(12345, username="dale", first_name="Dale", last_name="Rogers")
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM users WHERE user_id=?", (12345,)
        )
    assert len(rows) == 1
    assert rows[0]["username"] == "dale"


@pytest.mark.asyncio
async def test_upsert_user_updates_existing(db):
    """upsert_user should update last_seen_at and username on conflict."""
    await db.upsert_user(99, username="old")
    await db.upsert_user(99, username="new")
    async with db.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT username FROM users WHERE user_id=?", (99,)
        )
    assert rows[0]["username"] == "new"


@pytest.mark.asyncio
async def test_get_connection_raises_if_not_initialised(tmp_path):
    """Calling get_connection before init should raise RuntimeError."""
    manager = DatabaseManager(db_path=str(tmp_path / "noinit.db"))
    with pytest.raises(RuntimeError, match="not initialised"):
        async with manager.get_connection() as conn:
            pass


@pytest.mark.asyncio
async def test_double_init_idempotent(tmp_path):
    """Calling init twice should not raise (IF NOT EXISTS guards)."""
    manager = DatabaseManager(db_path=str(tmp_path / "idempotent.db"))
    await manager.init()
    await manager.init()  # should not raise
    await manager.close()


@pytest.mark.asyncio
async def test_fts_trigger_inserts_into_fts(db):
    """Inserting a fact row should auto-populate facts_fts via trigger."""
    await db.upsert_user(1)
    async with db.get_connection() as conn:
        await conn.execute(
            "INSERT INTO facts (user_id, category, content) VALUES (1, 'name', 'Alice')"
        )
        await conn.commit()
        rows = await conn.execute_fetchall(
            "SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'Alice'"
        )
    assert len(rows) >= 1
