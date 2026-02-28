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

CREATE TABLE IF NOT EXISTS background_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    job_type     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued',
    input_text   TEXT,
    result_text  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_background_jobs_user ON background_jobs(user_id, created_at);

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

CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_key TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'unknown',
    call_site TEXT NOT NULL DEFAULT 'router',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    fallback INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_calls_user_ts ON api_calls(user_id, timestamp);

-- Plan tracking (Phase 7+)
CREATE TABLE IF NOT EXISTS plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id),
    title        TEXT NOT NULL,
    description  TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_plans_user_status ON plans(user_id, status);

CREATE TABLE IF NOT EXISTS plan_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_plan_steps_plan ON plan_steps(plan_id);

CREATE TABLE IF NOT EXISTS plan_step_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id      INTEGER NOT NULL REFERENCES plan_steps(id) ON DELETE CASCADE,
    attempted_at TEXT NOT NULL DEFAULT (datetime('now')),
    outcome      TEXT NOT NULL,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS idx_plan_step_attempts_step ON plan_step_attempts(step_id);

-- File chunks for home directory RAG index (US-home-directory-rag)
CREATE TABLE IF NOT EXISTS file_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL,
    content_text TEXT NOT NULL,
    embedding_id INTEGER,
    file_mtime   REAL NOT NULL,
    indexed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uidx_file_chunks_path_chunk ON file_chunks(path, chunk_index);
CREATE INDEX IF NOT EXISTS idx_file_chunks_path ON file_chunks(path);

-- FTS5 virtual table for file chunk text search fallback
CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks_fts USING fts5(
    content_text,
    path,
    content=file_chunks,
    content_rowid=id
);

-- Outbound message queue for crash-recovery (OpenClaw pattern adoption)
CREATE TABLE IF NOT EXISTS outbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    reply_to_message_id INTEGER,
    parse_mode TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    sent_at TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbound_queue_status ON outbound_queue(status);
CREATE INDEX IF NOT EXISTS idx_outbound_queue_created ON outbound_queue(created_at);
"""


# Schema migrations applied after the main DDL.
# Each entry is attempted once; OperationalError means the column already exists.
_MIGRATIONS = [
    # 001: one-time reminder support
    "ALTER TABLE automations ADD COLUMN fire_at TEXT;",
    # 002: confidence score on knowledge items (added in model-orchestration-refactor)
    "ALTER TABLE knowledge ADD COLUMN confidence REAL DEFAULT 1.0;",
    # 003: backfill legacy facts rows — default 1.0 means "unreviewed", not "certain"
    "UPDATE facts SET confidence = 0.8 WHERE confidence = 1.0;",
    # 004: backfill legacy knowledge rows for the same reason
    "UPDATE knowledge SET confidence = 0.8 WHERE confidence = 1.0;",
    # 005: last_referenced_at for staleness tracking (US-improved-persistent-memory)
    "ALTER TABLE knowledge ADD COLUMN last_referenced_at TEXT;",
    # 006: backfill last_referenced_at from created_at
    "UPDATE knowledge SET last_referenced_at = created_at WHERE last_referenced_at IS NULL;",
    # 007: source_session for tracing facts back to conversations
    "ALTER TABLE knowledge ADD COLUMN source_session TEXT;",
    # 008-011: Per-phase timing columns for telemetry (US-telemetry-performance)
    "ALTER TABLE api_calls ADD COLUMN memory_injection_ms INTEGER DEFAULT 0;",
    "ALTER TABLE api_calls ADD COLUMN ttft_ms INTEGER DEFAULT 0;",
    "ALTER TABLE api_calls ADD COLUMN tool_execution_ms INTEGER DEFAULT 0;",
    "ALTER TABLE api_calls ADD COLUMN streaming_ms INTEGER DEFAULT 0;",
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

CREATE TRIGGER IF NOT EXISTS file_chunks_ai AFTER INSERT ON file_chunks BEGIN
    INSERT INTO file_chunks_fts(rowid, content_text, path) VALUES (new.id, new.content_text, new.path);
END;
CREATE TRIGGER IF NOT EXISTS file_chunks_ad AFTER DELETE ON file_chunks BEGIN
    INSERT INTO file_chunks_fts(file_chunks_fts, rowid, content_text, path) VALUES('delete', old.id, old.content_text, old.path);
END;
CREATE TRIGGER IF NOT EXISTS file_chunks_au AFTER UPDATE ON file_chunks BEGIN
    INSERT INTO file_chunks_fts(file_chunks_fts, rowid, content_text, path) VALUES('delete', old.id, old.content_text, old.path);
    INSERT INTO file_chunks_fts(rowid, content_text, path) VALUES (new.id, new.content_text, new.path);
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

        # Run incremental migrations (idempotent — OperationalError means already applied)
        for migration_sql in _MIGRATIONS:
            try:
                await self._conn.execute(migration_sql)
                await self._conn.commit()
            except aiosqlite.OperationalError as e:
                err = str(e).lower()
                if "already exists" not in err and "duplicate column" not in err:
                    logger.error(
                        "Migration failed unexpectedly (SQL: %.60s): %s",
                        migration_sql,
                        e,
                    )

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

    async def cleanup_old_api_calls(self, days: int = 90) -> int:
        """
        Delete api_calls records older than the specified number of days.
        
        Returns the number of rows deleted. This helps prevent unbounded
        database growth from telemetry data.
        """
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                DELETE FROM api_calls
                WHERE timestamp < datetime('now', ? || ' days')
                """,
                (f"-{days}",),
            )
            deleted = cursor.rowcount
            await conn.commit()
            if deleted > 0:
                logger.info("Cleaned up %d api_calls records older than %d days", deleted, days)
            return deleted

    async def cleanup_old_background_jobs(self, days: int = 30) -> int:
        """
        Delete completed background_jobs records older than the specified number of days.
        
        Only deletes jobs with status 'completed' or 'failed' to preserve
        in-progress work. Returns the number of rows deleted.
        """
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                DELETE FROM background_jobs
                WHERE created_at < datetime('now', ? || ' days')
                  AND status IN ('completed', 'failed')
                """,
                (f"-{days}",),
            )
            deleted = cursor.rowcount
            await conn.commit()
            if deleted > 0:
                logger.info("Cleaned up %d background_jobs records older than %d days", deleted, days)
            return deleted

    async def run_retention_cleanup(self) -> dict[str, int]:
        """
        Run all retention cleanup tasks.
        
        Returns a dict with the number of rows deleted from each table.
        Should be called periodically (e.g., daily from scheduler or startup).
        """
        results = {
            "api_calls": await self.cleanup_old_api_calls(days=90),
            "background_jobs": await self.cleanup_old_background_jobs(days=30),
        }
        return results
