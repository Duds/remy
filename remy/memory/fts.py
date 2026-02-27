"""
FTS5 full-text search — hybrid fallback when sqlite-vec is unavailable or
as a complement to ANN search for keyword precision.
"""

import logging
from typing import Any

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class FTSSearch:
    """BM25-ranked full-text search over facts and goals via SQLite FTS5."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    async def search_facts(
        self,
        user_id: int,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return facts matching `query` ranked by BM25 relevance."""
        if not query.strip():
            return []
        # Sanitise query: FTS5 treats special chars as operators
        safe_query = self._sanitise(query)
        async with self._db.get_connection() as conn:
            try:
                rows = await conn.execute_fetchall(
                    """
                    SELECT f.id, f.category, f.content, f.confidence,
                           bm25(facts_fts) AS score
                    FROM facts_fts
                    JOIN facts f ON f.id = facts_fts.rowid
                    WHERE facts_fts MATCH ? AND f.user_id = ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (safe_query, user_id, limit),
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.warning("FTS fact search failed: %s", e)
                return []

    async def search_goals(
        self,
        user_id: int,
        query: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return active goals matching `query` ranked by BM25 relevance."""
        if not query.strip():
            return []
        safe_query = self._sanitise(query)
        async with self._db.get_connection() as conn:
            try:
                rows = await conn.execute_fetchall(
                    """
                    SELECT g.id, g.title, g.description, g.status,
                           bm25(goals_fts) AS score
                    FROM goals_fts
                    JOIN goals g ON g.id = goals_fts.rowid
                    WHERE goals_fts MATCH ? AND g.user_id = ? AND g.status = 'active'
                    ORDER BY score
                    LIMIT ?
                    """,
                    (safe_query, user_id, limit),
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.warning("FTS goal search failed: %s", e)
                return []

    @staticmethod
    def _sanitise(query: str) -> str:
        """Escape FTS5 special characters and wrap tokens in quotes."""
        # Strip operators; wrap each token as a phrase
        tokens = query.split()
        safe_tokens = [f'"{t}"' for t in tokens if t and not t.startswith("-")]
        return " OR ".join(safe_tokens) if safe_tokens else query
