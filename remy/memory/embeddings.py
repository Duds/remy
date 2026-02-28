"""
Vector embedding store using sentence-transformers + sqlite-vec.

Lazy-loads the SentenceTransformer model on first use to avoid slow startup.
Model encode() runs in a thread executor to avoid blocking the asyncio event loop.
Falls back gracefully to FTS5 search when sqlite-vec is unavailable.
"""

import asyncio
import logging
import os
import threading
from typing import Any

from .database import SQLITE_VEC_AVAILABLE, DatabaseManager

logger = logging.getLogger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384

# Module-level singleton + lock: prevents concurrent model initialisation from
# the thread executor, which causes "Artifact already registered" errors in the
# HuggingFace tokenizers library when two threads try to load the same
# precompiled tokenizer simultaneously.
_model_instance = None
_model_lock = threading.Lock()

# Keep the torch inductor cache in a persistent user directory rather than
# /tmp, which can fill up and break the precompile step entirely.  The
# variable must be set before any part of sentence-transformers/torch is
# imported, so we configure it at module import time.  We also proactively
# clean up any stale `/tmp/torchinductor_*` directories on startup because the
# library sometimes falls back there if the env var isn't observed early
# enough (see issue #1234).
os.environ.setdefault(
    "TORCHINDUCTOR_CACHE_DIR",
    os.path.expanduser("~/.cache/torch/inductor"),
)


# --- housekeeping helpers ---------------------------------------------------

def _cleanup_tmp_cache() -> None:
    """Remove leftover torchinductor temp directories to avoid disk leaks.

    This runs automatically when the module is imported and again whenever an
    `OSError: [Errno 28] No space left on device` is thrown by the encoder.  On
    a container with limited /tmp, the cache can grow very large as each
    compile spits out a new folder (e.g. ``/tmp/torchinductor_remy``).  Deleting
    them lets the process recover without requiring a full restart.
    """
    import tempfile
    import shutil

    tmp_base = tempfile.gettempdir()
    for name in os.listdir(tmp_base):
        if name.startswith("torchinductor"):
            path = os.path.join(tmp_base, name)
            try:
                shutil.rmtree(path)
                logger.info("removed stale torchinductor cache %s", path)
            except Exception as e:  # pragma: no cover - best effort
                logger.warning("failed to remove %s: %s", path, e)


# perform one-off cleanup immediately
try:
    _cleanup_tmp_cache()
except Exception:  # pragma: no cover
    pass


def _load_model() -> "SentenceTransformer":  # noqa: F821
    """Load and warm up the SentenceTransformer (must be called under _model_lock)."""
    from sentence_transformers import SentenceTransformer

    logger.info("Loading SentenceTransformer model: %s …", _MODEL_NAME)
    model = SentenceTransformer(_MODEL_NAME)
    # Warm-up: trigger any JIT / tokenizer precompilation now, while we still
    # hold the lock, so concurrent callers never race during first-use compile.
    model.encode("warmup", normalize_embeddings=True)
    logger.info("Model loaded and warmed up")
    return model


class EmbeddingStore:
    """Manages text embeddings in SQLite using sqlite-vec for ANN search."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def _get_model(self):
        """Return the module-level SentenceTransformer singleton (thread-safe)."""
        global _model_instance
        if _model_instance is None:
            with _model_lock:
                if _model_instance is None:  # double-checked locking
                    _model_instance = _load_model()
        return _model_instance

    async def embed(self, text: str) -> list[float]:
        """Return a float32 embedding vector for `text` (runs in thread executor).

        If the underlying TorchInductor cache directory runs out of space we
        may see an ``OSError: [Errno 28] No space left on device`` from the
        encode call.  In that case the helper above will wipe any temporary
        cache directories and we retry once; if the second attempt still fails
        we propagate the error normally.
        """
        loop = asyncio.get_event_loop()

        def _do_encode():
            return self._get_model().encode(text, normalize_embeddings=True).tolist()

        try:
            embedding = await loop.run_in_executor(None, _do_encode)
        except OSError as e:  # pragma: no cover - path triggered empirically
            if e.errno == 28:  # no space
                logger.warning("disk full during embedding; cleaning tmp cache and retrying")
                _cleanup_tmp_cache()
                embedding = await loop.run_in_executor(None, _do_encode)
            else:
                raise
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
        recency_boost: bool = False,
    ) -> list[dict[str, Any]]:
        """ANN search filtered to a specific source_type (fact / goal / message).
        
        Args:
            recency_boost: If True, results from the last 30 days are weighted
                          higher by applying a distance penalty to older items.
        """
        if not SQLITE_VEC_AVAILABLE:
            return []

        vec = await self.embed(query)
        vec_bytes = self._vec_bytes(vec)

        async with self._db.get_connection() as conn:
            try:
                if recency_boost:
                    # Apply recency boost: items referenced in last 30 days get
                    # their distance reduced, older items get a penalty
                    rows = await conn.execute_fetchall(
                        """
                        SELECT e.id, e.source_type, e.source_id, e.content_text, ev.distance,
                               k.last_referenced_at,
                               CASE 
                                   WHEN k.last_referenced_at >= datetime('now', '-30 days') 
                                   THEN ev.distance * 0.8
                                   WHEN k.last_referenced_at >= datetime('now', '-90 days')
                                   THEN ev.distance * 1.0
                                   ELSE ev.distance * 1.2
                               END as boosted_distance
                        FROM embeddings_vec ev
                        JOIN embeddings e ON e.id = ev.rowid
                        LEFT JOIN knowledge k ON k.id = e.source_id AND e.source_type LIKE 'knowledge_%'
                        WHERE e.user_id = ? AND e.source_type = ?
                        ORDER BY boosted_distance
                        LIMIT ?
                        """,
                        (user_id, source_type, limit),
                    )
                else:
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
