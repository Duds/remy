"""
Vector embedding store using sentence-transformers + sqlite-vec.

Lazy-loads the SentenceTransformer model on first use to avoid slow startup.
Model encode() runs in a thread executor to avoid blocking the asyncio event loop.
Falls back gracefully to FTS5 search when sqlite-vec is unavailable.
"""

import asyncio
import logging
from typing import Any

from .database import SQLITE_VEC_AVAILABLE, DatabaseManager

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


class EmbeddingStore:
    """Manages text embeddings in SQLite using sqlite-vec for ANN search."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        self._model = None  # lazy-loaded

    def _get_model(self):
        """Lazy-load SentenceTransformer on first access."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading SentenceTransformer model: %s …", _MODEL_NAME)
            self._model = SentenceTransformer(_MODEL_NAME)
            logger.info("Model loaded")
        return self._model

    async def embed(self, text: str) -> list[float]:
        """Return a float32 embedding vector for `text` (runs in thread executor)."""
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: self._get_model().encode(text, normalize_embeddings=True).tolist(),
        )
        return embedding

    def _vec_bytes(self, embedding: list[float]) -> bytes:
        """Serialize float list to little-endian float32 bytes for sqlite-vec."""
        import struct
        return struct.pack(f"{len(embedding)}f", *embedding)

    async def upsert_embedding(
        self,
        user_id: int,
        source_type: str,
        source_id: int,
        text: str,
    ) -> int:
        """
        Store embedding for a fact, goal, or message.
        Returns the embedding row id.
        """
        vec = await self.embed(text)
        vec_bytes = self._vec_bytes(vec)

        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO embeddings (user_id, source_type, source_id, content_text, model_name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, source_type, source_id, text, _MODEL_NAME),
            )
            embedding_id = cursor.lastrowid

            if SQLITE_VEC_AVAILABLE:
                try:
                    await conn.execute(
                        "INSERT INTO embeddings_vec(rowid, embedding) VALUES (?, ?)",
                        (embedding_id, vec_bytes),
                    )
                except Exception as e:
                    logger.warning("Could not insert into embeddings_vec: %s", e)

            await conn.commit()

        return embedding_id

    async def search_similar(
        self,
        user_id: int,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Return up to `limit` most semantically similar embeddings for this user.
        Uses sqlite-vec ANN if available; falls back to returning empty list
        (caller should use FTS5 as fallback).
        """
        if not SQLITE_VEC_AVAILABLE:
            return []

        vec = await self.embed(query)
        vec_bytes = self._vec_bytes(vec)

        async with self._db.get_connection() as conn:
            try:
                rows = await conn.execute_fetchall(
                    """
                    SELECT e.id, e.source_type, e.source_id, e.content_text, ev.distance
                    FROM embeddings_vec ev
                    JOIN embeddings e ON e.id = ev.rowid
                    WHERE e.user_id = ?
                    ORDER BY ev.distance
                    LIMIT ?
                    """,
                    (user_id, limit),
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.warning("ANN search failed: %s", e)
                return []

    async def search_similar_for_type(
        self,
        user_id: int,
        query: str,
        source_type: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """ANN search filtered to a specific source_type (fact / goal / message)."""
        if not SQLITE_VEC_AVAILABLE:
            return []

        vec = await self.embed(query)
        vec_bytes = self._vec_bytes(vec)

        async with self._db.get_connection() as conn:
            try:
                rows = await conn.execute_fetchall(
                    """
                    SELECT e.id, e.source_type, e.source_id, e.content_text, ev.distance
                    FROM embeddings_vec ev
                    JOIN embeddings e ON e.id = ev.rowid
                    WHERE e.user_id = ? AND e.source_type = ?
                    ORDER BY ev.distance
                    LIMIT ?
                    """,
                    (user_id, source_type, limit),
                )
                return [dict(row) for row in rows]
            except Exception as e:
                logger.warning("ANN search failed: %s", e)
                return []
