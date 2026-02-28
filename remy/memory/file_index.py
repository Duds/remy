"""
Home directory RAG index — background file indexer for semantic search.

Walks ~/Projects and ~/Documents, chunks text files, embeds via EmbeddingStore,
and stores in file_chunks table for semantic search via search_files tool.

Incremental indexing: only re-indexes files whose mtime has changed.
Nightly scheduled via ProactiveScheduler; manual trigger via /reindex.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database import DatabaseManager
    from .embeddings import EmbeddingStore

logger = logging.getLogger(__name__)

# Chunking parameters
CHUNK_CHARS = 1500       # ~300 words, fits comfortably in context
OVERLAP_CHARS = 200      # overlap for context continuity at boundaries
MIN_CHUNK_CHARS = 50     # drop near-empty trailing chunks

# Default extensions to index (text-based files)
DEFAULT_INDEX_EXTENSIONS = {
    ".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".csv", ".html", ".css", ".sh", ".bash", ".zsh",
    ".rst", ".xml", ".ini", ".cfg", ".conf", ".env.example",
}

# Directories to skip during indexing
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    ".eggs", "*.egg-info", ".cache", ".idea", ".vscode",
}

# Maximum file size to index (500 KB)
MAX_FILE_SIZE = 500 * 1024

# Sensitive paths to never index
SENSITIVE_PATTERNS = {".env", ".ssh", ".aws", ".gnupg", "credentials", "secrets"}


@dataclass
class FileChunk:
    """A chunk of text from an indexed file."""
    id: int
    path: str
    chunk_index: int
    content_text: str
    embedding_id: int | None
    file_mtime: float
    indexed_at: str


@dataclass
class IndexStats:
    """Statistics about the file index."""
    files_indexed: int
    total_chunks: int
    last_run: str | None
    paths: list[str]
    extensions: list[str]


def chunk_text(text: str) -> list[str]:
    """
    Split text into overlapping chunks for embedding.
    
    Uses paragraph/sentence/word boundaries when possible to avoid
    cutting mid-word or mid-sentence.
    """
    text = text.strip()
    if not text:
        return []
    
    # Short text: return as single chunk
    if len(text) <= CHUNK_CHARS:
        return [text] if len(text) >= MIN_CHUNK_CHARS else []
    
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = min(start + CHUNK_CHARS, text_len)
        
        # Try to break at a natural boundary if not at end of text
        if end < text_len:
            # Try paragraph, then newline, then sentence, then space
            for sep in ("\n\n", "\n", ". ", " "):
                pos = text.rfind(sep, start, end)
                if pos > start + CHUNK_CHARS // 2:
                    end = pos + len(sep)
                    break
        
        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(chunk)
        
        # Move start forward with overlap
        start = end - OVERLAP_CHARS if end < text_len else text_len
    
    return chunks


def _is_binary(content: bytes) -> bool:
    """Check if content appears to be binary (contains null bytes)."""
    return b"\x00" in content[:8192]


def _is_sensitive_path(path: Path) -> bool:
    """Check if path contains sensitive patterns."""
    path_str = str(path).lower()
    return any(pattern in path_str for pattern in SENSITIVE_PATTERNS)


def _should_skip_dir(name: str) -> bool:
    """Check if directory should be skipped."""
    return name in SKIP_DIRS or name.startswith(".")


class FileChunkStore:
    """CRUD operations for file chunks in SQLite."""
    
    def __init__(self, db: "DatabaseManager") -> None:
        self._db = db
    
    async def save_chunk(
        self,
        path: str,
        chunk_index: int,
        content_text: str,
        embedding_id: int | None,
        file_mtime: float,
    ) -> int:
        """Save or update a file chunk."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO file_chunks (path, chunk_index, content_text, embedding_id, file_mtime)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path, chunk_index) DO UPDATE SET
                    content_text = excluded.content_text,
                    embedding_id = excluded.embedding_id,
                    file_mtime = excluded.file_mtime,
                    indexed_at = datetime('now')
                """,
                (path, chunk_index, content_text, embedding_id, file_mtime),
            )
            await conn.commit()
            return cursor.lastrowid or 0
    
    async def delete_chunks_for_file(self, path: str) -> int:
        """Delete all chunks for a file. Returns count deleted."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM file_chunks WHERE path = ?",
                (path,),
            )
            await conn.commit()
            return cursor.rowcount
    
    async def delete_chunks_above_index(self, path: str, max_index: int) -> int:
        """Delete chunks with index > max_index (for files that got shorter)."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM file_chunks WHERE path = ? AND chunk_index > ?",
                (path, max_index),
            )
            await conn.commit()
            return cursor.rowcount
    
    async def get_all_indexed_paths(self) -> dict[str, float]:
        """Return dict of path -> mtime for all indexed files."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                "SELECT DISTINCT path, file_mtime FROM file_chunks"
            )
            return {row["path"]: row["file_mtime"] for row in rows}
    
    async def search_chunks(
        self,
        query_embedding: list[float],
        limit: int = 5,
        path_filter: str | None = None,
    ) -> list[dict]:
        """
        Search for chunks similar to the query embedding.
        
        Uses sqlite-vec ANN if available, otherwise falls back to FTS5.
        """
        from .database import SQLITE_VEC_AVAILABLE
        
        async with self._db.get_connection() as conn:
            if SQLITE_VEC_AVAILABLE:
                # ANN search via sqlite-vec
                import struct
                vec_bytes = struct.pack(f"{len(query_embedding)}f", *query_embedding)
                
                if path_filter:
                    rows = await conn.execute_fetchall(
                        """
                        SELECT fc.id, fc.path, fc.chunk_index, fc.content_text, ev.distance
                        FROM embeddings_vec ev
                        JOIN embeddings e ON e.id = ev.rowid
                        JOIN file_chunks fc ON fc.embedding_id = e.id
                        WHERE fc.path LIKE ?
                        ORDER BY ev.distance
                        LIMIT ?
                        """,
                        (f"{path_filter}%", limit),
                    )
                else:
                    rows = await conn.execute_fetchall(
                        """
                        SELECT fc.id, fc.path, fc.chunk_index, fc.content_text, ev.distance
                        FROM embeddings_vec ev
                        JOIN embeddings e ON e.id = ev.rowid
                        JOIN file_chunks fc ON fc.embedding_id = e.id
                        ORDER BY ev.distance
                        LIMIT ?
                        """,
                        (limit,),
                    )
                return [dict(row) for row in rows]
            else:
                # FTS5 fallback — not as good but works
                logger.debug("Using FTS5 fallback for file search")
                return []
    
    async def search_chunks_fts(
        self,
        query: str,
        limit: int = 5,
        path_filter: str | None = None,
    ) -> list[dict]:
        """FTS5 text search fallback when sqlite-vec unavailable."""
        async with self._db.get_connection() as conn:
            # Simple LIKE search as fallback
            query_pattern = f"%{query}%"
            if path_filter:
                rows = await conn.execute_fetchall(
                    """
                    SELECT id, path, chunk_index, content_text
                    FROM file_chunks
                    WHERE content_text LIKE ? AND path LIKE ?
                    LIMIT ?
                    """,
                    (query_pattern, f"{path_filter}%", limit),
                )
            else:
                rows = await conn.execute_fetchall(
                    """
                    SELECT id, path, chunk_index, content_text
                    FROM file_chunks
                    WHERE content_text LIKE ?
                    LIMIT ?
                    """,
                    (query_pattern, limit),
                )
            return [dict(row) for row in rows]
    
    async def get_stats(self) -> tuple[int, int, str | None]:
        """Return (file_count, chunk_count, last_indexed_at)."""
        async with self._db.get_connection() as conn:
            row = await conn.execute_fetchall(
                """
                SELECT 
                    COUNT(DISTINCT path) as file_count,
                    COUNT(*) as chunk_count,
                    MAX(indexed_at) as last_indexed
                FROM file_chunks
                """
            )
            if row:
                r = row[0]
                return r["file_count"], r["chunk_count"], r["last_indexed"]
            return 0, 0, None


class FileIndexer:
    """
    Background file indexer for home directory RAG.
    
    Walks configured paths, chunks text files, embeds via EmbeddingStore,
    and stores in file_chunks table for semantic search.
    """
    
    def __init__(
        self,
        db: "DatabaseManager",
        embeddings: "EmbeddingStore",
        index_paths: list[str] | None = None,
        index_extensions: set[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self._db = db
        self._embeddings = embeddings
        self._chunk_store = FileChunkStore(db)
        self._index_paths = index_paths or [
            str(Path.home() / "Projects"),
            str(Path.home() / "Documents"),
        ]
        self._index_extensions = index_extensions or DEFAULT_INDEX_EXTENSIONS
        self._enabled = enabled
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @property
    def index_paths(self) -> list[str]:
        return self._index_paths
    
    @property
    def index_extensions(self) -> set[str]:
        return self._index_extensions
    
    async def run_incremental(self) -> dict:
        """
        Run incremental indexing — only process new/modified files.
        
        Returns dict with stats: files_indexed, chunks_created, files_removed, errors.
        """
        if not self._enabled:
            return {"status": "disabled"}
        
        stats = {
            "files_indexed": 0,
            "chunks_created": 0,
            "files_removed": 0,
            "files_skipped": 0,
            "errors": 0,
        }
        
        logger.info("Starting incremental file index...")
        start_time = datetime.now(timezone.utc)
        
        # Get currently indexed files
        indexed_files = await self._chunk_store.get_all_indexed_paths()
        seen_paths: set[str] = set()
        
        # Walk all index paths
        for base_path in self._index_paths:
            base = Path(base_path)
            if not base.exists():
                logger.debug("Index path does not exist: %s", base_path)
                continue
            
            for file_path in self._walk_files(base):
                path_str = str(file_path)
                seen_paths.add(path_str)
                
                try:
                    file_stat = file_path.stat()
                    file_mtime = file_stat.st_mtime
                    
                    # Skip if not modified since last index
                    if path_str in indexed_files:
                        if abs(indexed_files[path_str] - file_mtime) < 1.0:
                            stats["files_skipped"] += 1
                            continue
                    
                    # Index the file
                    chunks_created = await self._index_file(file_path, file_mtime)
                    if chunks_created > 0:
                        stats["files_indexed"] += 1
                        stats["chunks_created"] += chunks_created
                    
                except Exception as e:
                    logger.warning("Error indexing %s: %s", file_path, e)
                    stats["errors"] += 1
        
        # Remove chunks for deleted files
        for old_path in indexed_files:
            if old_path not in seen_paths:
                deleted = await self._chunk_store.delete_chunks_for_file(old_path)
                if deleted > 0:
                    stats["files_removed"] += 1
                    logger.debug("Removed %d chunks for deleted file: %s", deleted, old_path)
        
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            "File index complete in %.1fs: %d files indexed, %d chunks created, "
            "%d files removed, %d skipped, %d errors",
            elapsed,
            stats["files_indexed"],
            stats["chunks_created"],
            stats["files_removed"],
            stats["files_skipped"],
            stats["errors"],
        )
        
        return stats
    
    def _walk_files(self, base: Path):
        """
        Generator that yields indexable files under base path.
        
        Skips hidden directories, node_modules, __pycache__, etc.
        """
        try:
            for entry in base.iterdir():
                if entry.is_dir():
                    if _should_skip_dir(entry.name):
                        continue
                    yield from self._walk_files(entry)
                elif entry.is_file():
                    if self._should_index_file(entry):
                        yield entry
        except PermissionError:
            logger.debug("Permission denied: %s", base)
        except Exception as e:
            logger.debug("Error walking %s: %s", base, e)
    
    def _should_index_file(self, path: Path) -> bool:
        """Check if a file should be indexed."""
        # Check extension
        if path.suffix.lower() not in self._index_extensions:
            return False
        
        # Check for sensitive paths
        if _is_sensitive_path(path):
            return False
        
        # Check file size
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                return False
        except OSError:
            return False
        
        return True
    
    async def _index_file(self, path: Path, mtime: float) -> int:
        """
        Index a single file: read, chunk, embed, store.
        
        Returns number of chunks created.
        """
        # Read file content
        def _read():
            with open(path, "rb") as f:
                content = f.read()
            if _is_binary(content):
                return None
            return content.decode("utf-8", errors="replace")
        
        try:
            content = await asyncio.to_thread(_read)
        except Exception as e:
            logger.debug("Could not read %s: %s", path, e)
            return 0
        
        if content is None:
            logger.debug("Skipping binary file: %s", path)
            return 0
        
        if not content.strip():
            return 0
        
        # Chunk the content
        chunks = chunk_text(content)
        if not chunks:
            return 0
        
        path_str = str(path)
        chunks_created = 0
        
        # Embed and store each chunk
        for idx, chunk_text_content in enumerate(chunks):
            try:
                # Create embedding
                embedding_id = await self._embeddings.upsert_embedding(
                    user_id=0,  # File chunks are user-agnostic
                    source_type="file_chunk",
                    source_id=0,  # Will be updated after chunk save
                    text=chunk_text_content[:500],  # Embed first 500 chars for efficiency
                )
                
                # Save chunk
                await self._chunk_store.save_chunk(
                    path=path_str,
                    chunk_index=idx,
                    content_text=chunk_text_content,
                    embedding_id=embedding_id,
                    file_mtime=mtime,
                )
                chunks_created += 1
                
            except Exception as e:
                logger.warning("Error embedding chunk %d of %s: %s", idx, path, e)
        
        # Clean up any old chunks beyond current count
        await self._chunk_store.delete_chunks_above_index(path_str, len(chunks) - 1)
        
        logger.debug("Indexed %s: %d chunks", path, chunks_created)
        return chunks_created
    
    async def search(
        self,
        query: str,
        limit: int = 5,
        path_filter: str | None = None,
    ) -> list[dict]:
        """
        Search indexed files for content matching query.
        
        Uses semantic search via embeddings if available, falls back to FTS.
        """
        if not self._enabled:
            return []
        
        from .database import SQLITE_VEC_AVAILABLE
        
        # Expand ~ in path filter
        if path_filter:
            path_filter = str(Path(path_filter).expanduser())
        
        if SQLITE_VEC_AVAILABLE:
            # Semantic search
            try:
                query_embedding = await self._embeddings.embed(query)
                results = await self._chunk_store.search_chunks(
                    query_embedding, limit=limit, path_filter=path_filter
                )
                if results:
                    return results
            except Exception as e:
                logger.warning("Semantic search failed, falling back to FTS: %s", e)
        
        # FTS fallback
        return await self._chunk_store.search_chunks_fts(
            query, limit=limit, path_filter=path_filter
        )
    
    async def get_status(self) -> IndexStats:
        """Get current index status."""
        file_count, chunk_count, last_run = await self._chunk_store.get_stats()
        return IndexStats(
            files_indexed=file_count,
            total_chunks=chunk_count,
            last_run=last_run,
            paths=self._index_paths,
            extensions=sorted(self._index_extensions),
        )
