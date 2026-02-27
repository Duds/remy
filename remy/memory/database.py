"""
SQLite database manager for remy.

Initialises schema (users, facts, goals, embeddings, photos, FTS5 virtual tables).
Loads the sqlite-vec extension for ANN vector search with graceful fallback.
Uses WAL mode for concurrent read safety with single-writer asyncio pattern.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

from ..config import settings

logger = logging.getLogger(__name__)

# Flag set at init time; if False, vector search falls back to FTS5
SQLITE_VEC_AVAILABLE = False


_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    last_name    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(user_id),
    session_key   TEXT NOT NULL,
    summary       TEXT,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at      TEXT,
    message_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);

CREATE TABLE IF NOT EXISTS facts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    category     TEXT NOT NULL,
    content      TEXT NOT NULL,
    confidence   REAL DEFAULT 1.0,
    embedding_id INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id, category);

CREATE TABLE IF NOT EXISTS goals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    title        TEXT NOT NULL,
    description  TEXT,
    status       TEXT DEFAULT 'active',
    embedding_id INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_goals_user_status ON goals(user_id, status);

CREATE TABLE IF NOT EXISTS knowledge (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    entity_type  TEXT NOT NULL,
    content      TEXT NOT NULL,
    metadata     TEXT NOT NULL DEFAULT '{}',
    confidence   REAL DEFAULT 1.0,
    embedding_id INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_knowledge_user_type ON knowledge(user_id, entity_type);

CREATE TABLE IF NOT EXISTS embeddings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    source_type  TEXT NOT NULL,
    source_id    INTEGER,
    content_text TEXT NOT NULL,
    model_name   TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS photos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    telegram_file_id TEXT NOT NULL,
    caption          TEXT,
    image_blob       BLOB,
    embedding_id     INTEGER,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS automations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    label        TEXT NOT NULL,
    cron         TEXT NOT NULL,
    last_run_at  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_automations_user ON automations(user_id);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    content,
    category,
    content=facts,
    content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS goals_fts USING fts5(
    title,
    description,
    content=goals,
    content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    content,
    entity_type,
    content=knowledge,
    content_rowid=id
);
"""

# Schema migrations applied after the main DDL.
# Each entry is attempted once; OperationalError means the column already exists.
_MIGRATIONS = [
    # 001: one-time reminder support
    "ALTER TABLE automations ADD COLUMN fire_at TEXT;",
    # 002: confidence score on knowledge items (added in model-orchestration-refactor)
    "ALTER TABLE knowledge ADD COLUMN confidence REAL DEFAULT 1.0;",
]

# Triggers to keep FTS indices in sync with source tables
_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, category) VALUES (new.id, new.content, new.category);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, category) VALUES('delete', old.id, old.content, old.category);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, category) VALUES('delete', old.id, old.content, old.category);
    INSERT INTO facts_fts(rowid, content, category) VALUES (new.id, new.content, new.category);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, content, entity_type) VALUES (new.id, new.content, new.entity_type);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, entity_type) VALUES('delete', old.id, old.content, old.entity_type);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, content, entity_type) VALUES('delete', old.id, old.content, old.entity_type);
    INSERT INTO knowledge_fts(rowid, content, entity_type) VALUES (new.id, new.content, new.entity_type);
END;

CREATE TRIGGER IF NOT EXISTS goals_ai AFTER INSERT ON goals BEGIN
    INSERT INTO goals_fts(rowid, title, description) VALUES (new.id, new.title, COALESCE(new.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS goals_ad AFTER DELETE ON goals BEGIN
    INSERT INTO goals_fts(goals_fts, rowid, title, description) VALUES('delete', old.id, old.title, COALESCE(old.description, ''));
END;
CREATE TRIGGER IF NOT EXISTS goals_au AFTER UPDATE ON goals BEGIN
    INSERT INTO goals_fts(goals_fts, rowid, title, description) VALUES('delete', old.id, old.title, COALESCE(old.description, ''));
    INSERT INTO goals_fts(rowid, title, description) VALUES (new.id, new.title, COALESCE(new.description, ''));
END;
"""

# sqlite-vec virtual table (created only if extension loads successfully)
_VEC_TABLE_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS embeddings_vec USING vec0(
    embedding float[384]
);
"""


class DatabaseManager:
    """Manages the SQLite connection and schema for remy."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open connection, load extensions, run DDL."""
        global SQLITE_VEC_AVAILABLE
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

        # Try loading sqlite-vec for ANN search
        try:
            import sqlite_vec
            await self._conn.enable_load_extension(True)
            await self._conn.execute("SELECT load_extension(?)", (sqlite_vec.loadable_path(),))
            await self._conn.enable_load_extension(False)
            SQLITE_VEC_AVAILABLE = True
            logger.info("sqlite-vec loaded — ANN vector search enabled")
        except Exception as e:
            logger.warning("sqlite-vec unavailable (%s) — falling back to FTS5 search", e)
            SQLITE_VEC_AVAILABLE = False

        # Run schema DDL
        await self._conn.executescript(_DDL)
        await self._conn.executescript(_FTS_TRIGGERS)

        if SQLITE_VEC_AVAILABLE:
            try:
                await self._conn.executescript(_VEC_TABLE_DDL)
            except Exception as e:
                logger.warning("Could not create embeddings_vec table: %s", e)
                SQLITE_VEC_AVAILABLE = False

        # Run incremental migrations (idempotent — errors mean already applied)
        for migration_sql in _MIGRATIONS:
            try:
                await self._conn.execute(migration_sql)
                await self._conn.commit()
            except Exception:
                pass  # Column/index already exists

        await self._conn.commit()
        logger.info("Database initialised: %s", self.db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[aiosqlite.Connection]:
        """Yield the shared connection. Callers must not close it."""
        if self._conn is None:
            raise RuntimeError("DatabaseManager not initialised — call init() first")
        yield self._conn

    async def upsert_user(
        self,
        user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> None:
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    last_seen_at=datetime('now')
                """,
                (user_id, username, first_name, last_name),
            )
            await conn.commit()
