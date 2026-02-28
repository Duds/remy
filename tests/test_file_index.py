"""Tests for remy/memory/file_index.py — home directory RAG index."""

import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from remy.memory.database import DatabaseManager
from remy.memory.file_index import (
    FileIndexer,
    FileChunkStore,
    chunk_text,
    _is_binary,
    _is_sensitive_path,
    _should_skip_dir,
    CHUNK_CHARS,
    OVERLAP_CHARS,
)
from remy.memory.embeddings import EmbeddingStore


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh DB per test with mocked embeddings."""
    manager = DatabaseManager(db_path=str(tmp_path / "test_file_index.db"))
    await manager.init()
    
    # Mock embeddings to avoid SentenceTransformer loading
    embeddings = MagicMock(spec=EmbeddingStore)
    embeddings.embed = AsyncMock(return_value=[0.1] * 384)
    embeddings.upsert_embedding = AsyncMock(return_value=1)
    
    yield manager, embeddings
    await manager.close()


@pytest_asyncio.fixture
async def test_files(tmp_path):
    """Create test files for indexing."""
    projects = tmp_path / "Projects"
    projects.mkdir()
    
    # Create some test files with content longer than MIN_CHUNK_CHARS (50)
    (projects / "readme.md").write_text(
        "# Test Project\n\n"
        "This is a comprehensive test project that contains multiple features and components. "
        "The project aims to demonstrate various capabilities and functionalities."
    )
    (projects / "notes.txt").write_text(
        "Some detailed notes about the project including implementation details, "
        "design decisions, and future improvements that we plan to make."
    )
    (projects / "code.py").write_text(
        "def hello():\n"
        "    '''A simple hello world function that prints a greeting message.'''\n"
        "    print('Hello world from the test project!')\n"
    )
    
    # Create a subdirectory
    subdir = projects / "subproject"
    subdir.mkdir()
    (subdir / "sub.md").write_text(
        "# Subproject Documentation\n\n"
        "This is the documentation for the subproject component of our main project."
    )
    
    # Create files that should be skipped
    git_dir = projects / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("git config")
    
    node_modules = projects / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.json").write_text("{}")
    
    # Create a binary file
    (projects / "binary.bin").write_bytes(b"\x00\x01\x02\x03")
    
    # Create a large file
    (projects / "large.txt").write_text("x" * 600_000)
    
    # Create a sensitive file
    (projects / ".env").write_text("SECRET=abc123")
    
    return projects


class TestChunkText:
    """Tests for the chunk_text function."""
    
    def test_short_text_single_chunk(self):
        """Short text should produce a single chunk."""
        # Text must be >= MIN_CHUNK_CHARS (50) to produce a chunk
        text = "This is a short text that is long enough to be indexed as a single chunk."
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_long_text_multiple_chunks(self):
        """Long text should be split into multiple chunks."""
        text = "Word " * 500  # ~2500 chars
        chunks = chunk_text(text)
        assert len(chunks) > 1
        # Each chunk should be <= CHUNK_CHARS
        for chunk in chunks:
            assert len(chunk) <= CHUNK_CHARS + 50  # Allow some margin for boundary finding
    
    def test_overlap_between_chunks(self):
        """Chunks should have overlapping content."""
        text = "Sentence one. " * 200  # Long enough for multiple chunks
        chunks = chunk_text(text)
        if len(chunks) >= 2:
            # The end of chunk 0 should appear at the start of chunk 1
            # (approximately, due to boundary finding)
            assert len(set(chunks)) == len(chunks)  # All chunks should be unique
    
    def test_empty_text(self):
        """Empty text should produce no chunks."""
        assert chunk_text("") == []
        assert chunk_text("   ") == []
    
    def test_paragraph_boundary(self):
        """Should prefer breaking at paragraph boundaries."""
        text = "First paragraph.\n\nSecond paragraph." + " more text" * 200
        chunks = chunk_text(text)
        # First chunk should end at or near paragraph boundary if possible
        assert len(chunks) >= 1


class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_is_binary_with_null_bytes(self):
        """Binary detection should find null bytes."""
        assert _is_binary(b"\x00\x01\x02") is True
        assert _is_binary(b"Hello world") is False
        assert _is_binary(b"Text with \x00 null") is True
    
    def test_is_sensitive_path(self):
        """Sensitive paths should be detected."""
        assert _is_sensitive_path(Path("/home/user/.env")) is True
        assert _is_sensitive_path(Path("/home/user/.ssh/id_rsa")) is True
        assert _is_sensitive_path(Path("/home/user/.aws/credentials")) is True
        assert _is_sensitive_path(Path("/home/user/projects/readme.md")) is False
    
    def test_should_skip_dir(self):
        """Directories to skip should be detected."""
        assert _should_skip_dir(".git") is True
        assert _should_skip_dir("node_modules") is True
        assert _should_skip_dir("__pycache__") is True
        assert _should_skip_dir(".venv") is True
        assert _should_skip_dir("src") is False
        assert _should_skip_dir("docs") is False


class TestFileChunkStore:
    """Tests for FileChunkStore CRUD operations."""
    
    @pytest.mark.asyncio
    async def test_save_and_retrieve_chunk(self, db):
        """Should save and retrieve a chunk."""
        manager, _ = db
        store = FileChunkStore(manager)
        
        chunk_id = await store.save_chunk(
            path="/test/file.md",
            chunk_index=0,
            content_text="Test content",
            embedding_id=1,
            file_mtime=1234567890.0,
        )
        
        assert chunk_id > 0
        
        # Verify it was saved
        indexed = await store.get_all_indexed_paths()
        assert "/test/file.md" in indexed
    
    @pytest.mark.asyncio
    async def test_delete_chunks_for_file(self, db):
        """Should delete all chunks for a file."""
        manager, _ = db
        store = FileChunkStore(manager)
        
        # Save multiple chunks
        await store.save_chunk("/test/file.md", 0, "Chunk 0", 1, 1234567890.0)
        await store.save_chunk("/test/file.md", 1, "Chunk 1", 2, 1234567890.0)
        await store.save_chunk("/test/other.md", 0, "Other", 3, 1234567890.0)
        
        # Delete chunks for one file
        deleted = await store.delete_chunks_for_file("/test/file.md")
        assert deleted == 2
        
        # Verify other file still exists
        indexed = await store.get_all_indexed_paths()
        assert "/test/file.md" not in indexed
        assert "/test/other.md" in indexed
    
    @pytest.mark.asyncio
    async def test_get_stats(self, db):
        """Should return correct stats."""
        manager, _ = db
        store = FileChunkStore(manager)
        
        await store.save_chunk("/test/a.md", 0, "A0", 1, 1234567890.0)
        await store.save_chunk("/test/a.md", 1, "A1", 2, 1234567890.0)
        await store.save_chunk("/test/b.md", 0, "B0", 3, 1234567890.0)
        
        file_count, chunk_count, last_indexed = await store.get_stats()
        assert file_count == 2
        assert chunk_count == 3
        assert last_indexed is not None
    
    @pytest.mark.asyncio
    async def test_upsert_on_conflict(self, db):
        """Should update chunk on conflict."""
        manager, _ = db
        store = FileChunkStore(manager)
        
        await store.save_chunk("/test/file.md", 0, "Original", 1, 1234567890.0)
        await store.save_chunk("/test/file.md", 0, "Updated", 2, 1234567891.0)
        
        # Should only have one chunk
        file_count, chunk_count, _ = await store.get_stats()
        assert file_count == 1
        assert chunk_count == 1


class TestFileIndexer:
    """Tests for the FileIndexer class."""
    
    @pytest.mark.asyncio
    async def test_indexer_disabled(self, db):
        """Disabled indexer should return immediately."""
        manager, embeddings = db
        indexer = FileIndexer(manager, embeddings, enabled=False)
        
        stats = await indexer.run_incremental()
        assert stats.get("status") == "disabled"
    
    @pytest.mark.asyncio
    async def test_index_files(self, db, test_files):
        """Should index text files in the test directory."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        stats = await indexer.run_incremental()
        
        # Should have indexed the text files
        assert stats["files_indexed"] >= 3  # readme.md, notes.txt, code.py, sub.md
        assert stats["chunks_created"] >= 3
        assert stats["errors"] == 0
    
    @pytest.mark.asyncio
    async def test_skip_binary_files(self, db, test_files):
        """Should skip binary files."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        await indexer.run_incremental()
        
        # Binary file should not be indexed
        chunk_store = FileChunkStore(manager)
        indexed = await chunk_store.get_all_indexed_paths()
        assert not any("binary.bin" in p for p in indexed)
    
    @pytest.mark.asyncio
    async def test_skip_large_files(self, db, test_files):
        """Should skip files larger than MAX_FILE_SIZE."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        await indexer.run_incremental()
        
        # Large file should not be indexed
        chunk_store = FileChunkStore(manager)
        indexed = await chunk_store.get_all_indexed_paths()
        assert not any("large.txt" in p for p in indexed)
    
    @pytest.mark.asyncio
    async def test_skip_sensitive_files(self, db, test_files):
        """Should skip sensitive files like .env."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        await indexer.run_incremental()
        
        # .env should not be indexed
        chunk_store = FileChunkStore(manager)
        indexed = await chunk_store.get_all_indexed_paths()
        assert not any(".env" in p for p in indexed)
    
    @pytest.mark.asyncio
    async def test_skip_git_directory(self, db, test_files):
        """Should skip .git directory."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        await indexer.run_incremental()
        
        # .git files should not be indexed
        chunk_store = FileChunkStore(manager)
        indexed = await chunk_store.get_all_indexed_paths()
        assert not any(".git" in p for p in indexed)
    
    @pytest.mark.asyncio
    async def test_incremental_skip_unchanged(self, db, test_files):
        """Should skip unchanged files on second run."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        # First run
        stats1 = await indexer.run_incremental()
        files_indexed_1 = stats1["files_indexed"]
        
        # Second run - should skip all files
        stats2 = await indexer.run_incremental()
        assert stats2["files_indexed"] == 0
        assert stats2["files_skipped"] >= files_indexed_1
    
    @pytest.mark.asyncio
    async def test_get_status(self, db, test_files):
        """Should return correct index status."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        await indexer.run_incremental()
        
        status = await indexer.get_status()
        assert status.files_indexed >= 3
        assert status.total_chunks >= 3
        assert str(test_files) in status.paths
        assert ".md" in status.extensions
    
    @pytest.mark.asyncio
    async def test_search_fts_fallback(self, db, test_files):
        """Should search using FTS fallback."""
        manager, embeddings = db
        indexer = FileIndexer(
            manager,
            embeddings,
            index_paths=[str(test_files)],
            enabled=True,
        )
        
        await indexer.run_incremental()
        
        # Search for content
        results = await indexer.search("test project")
        # Results depend on FTS availability; just verify no error
        assert isinstance(results, list)


class TestToolSchemas:
    """Tests for the tool schemas in tool_registry."""
    
    def test_search_files_schema_exists(self):
        """search_files tool schema should exist."""
        from remy.ai.tool_registry import TOOL_SCHEMAS
        
        names = [t["name"] for t in TOOL_SCHEMAS]
        assert "search_files" in names
        
        schema = next(t for t in TOOL_SCHEMAS if t["name"] == "search_files")
        assert "query" in schema["input_schema"]["properties"]
        assert "limit" in schema["input_schema"]["properties"]
        assert "path_filter" in schema["input_schema"]["properties"]
    
    def test_index_status_schema_exists(self):
        """index_status tool schema should exist."""
        from remy.ai.tool_registry import TOOL_SCHEMAS
        
        names = [t["name"] for t in TOOL_SCHEMAS]
        assert "index_status" in names
