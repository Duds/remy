"""
Tests for MemoryInjector's project context extraction logic.
Verifies that README.md files are read correctly from tracked projects.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from remy.memory.injector import MemoryInjector

@pytest.fixture
def mock_components():
    return {
        "db": MagicMock(),
        "embeddings": MagicMock(),
        "knowledge_store": MagicMock(),
        "fts": MagicMock(),
    }

@pytest.mark.asyncio
async def test_get_project_context_reads_readme(tmp_path, mock_components):
    # Setup: Create a fake project with a README
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    readme = project_dir / "README.md"
    readme.write_text("Hello from README", encoding="utf-8")
    
    # Mock DatabaseManager to return this project
    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [{"content": str(project_dir)}]
    
    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock
    
    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"]
    )
    
    # Execution
    results = await injector._get_project_context(user_id=1)
    
    # Assertions
    assert len(results) == 1
    assert "Hello from README" in results[0]["content"]
    assert str(project_dir) in results[0]["content"]
    assert results[0]["category"] == "project_context"

@pytest.mark.asyncio
async def test_get_project_context_handles_missing_readme(tmp_path, mock_components):
    # Setup: Project exists but no README
    project_dir = tmp_path / "empty_project"
    project_dir.mkdir()

    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [{"content": str(project_dir)}]

    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock

    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"]
    )

    # Execution
    results = await injector._get_project_context(user_id=1)

    # Assertions
    assert len(results) == 0


# --------------------------------------------------------------------------- #
# Bug 8 regression tests — [Errno 36] File name too long                      #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_get_project_context_skips_long_descriptive_text(mock_components):
    """
    Bug 8: A fact stored as category='project' containing a long description
    (not a filesystem path) must be silently skipped, not raise OSError [Errno 36].
    """
    long_description = (
        "Working on a personal AI assistant called Remy that uses Claude as its backend "
        "and Telegram as the interface, with various tools for Gmail, Calendar, web search, "
        "voice transcription, and persistent memory via SQLite vector embeddings. "
        "The project is structured as a Python package with APScheduler for proactive tasks."
    )
    assert len(long_description) > 255  # ensure it triggers the bug without the fix

    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [{"content": long_description}]

    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock

    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"],
    )

    # Must not raise, must return empty
    results = await injector._get_project_context(user_id=1)
    assert results == []


@pytest.mark.asyncio
async def test_get_project_context_skips_non_absolute_path(mock_components):
    """
    Relative paths and plain names stored as category='project' facts
    must be skipped — only absolute paths are valid project directories.
    """
    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [
        {"content": "relative/path/to/project"},
        {"content": "just a project name"},
    ]

    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock

    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"],
    )

    results = await injector._get_project_context(user_id=1)
    assert results == []


@pytest.mark.asyncio
async def test_get_project_context_skips_path_with_oversized_component(mock_components):
    """
    A path whose single component is exactly 256 bytes must be skipped.
    This is the minimum case that triggers [Errno 36] on Linux.
    """
    oversized_component = "a" * 256
    bad_path = f"/home/user/{oversized_component}"

    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [{"content": bad_path}]

    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock

    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"],
    )

    results = await injector._get_project_context(user_id=1)
    assert results == []


@pytest.mark.asyncio
async def test_get_project_context_accepts_valid_absolute_path(tmp_path, mock_components):
    """
    A valid absolute path with a README.md must still be processed correctly
    after the validation guards are in place.
    """
    project_dir = tmp_path / "valid_project"
    project_dir.mkdir()
    (project_dir / "README.md").write_text("Valid project readme", encoding="utf-8")

    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [{"content": str(project_dir)}]

    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock

    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"],
    )

    results = await injector._get_project_context(user_id=1)
    assert len(results) == 1
    assert "Valid project readme" in results[0]["content"]


@pytest.mark.asyncio
async def test_get_project_context_mixed_valid_and_invalid(tmp_path, mock_components):
    """
    When the DB returns a mix of valid paths and invalid descriptive text,
    only the valid paths should produce results.
    """
    project_dir = tmp_path / "good_project"
    project_dir.mkdir()
    (project_dir / "README.md").write_text("Good project", encoding="utf-8")

    long_description = "This is a descriptive project fact, not a path. " * 10

    db_mock = mock_components["db"]
    conn_mock = AsyncMock()
    conn_mock.execute_fetchall.return_value = [
        {"content": long_description},
        {"content": str(project_dir)},
    ]

    cm_mock = MagicMock()
    cm_mock.__aenter__.return_value = conn_mock
    db_mock.get_connection.return_value = cm_mock

    injector = MemoryInjector(
        db_mock,
        mock_components["embeddings"],
        mock_components["knowledge_store"],
        mock_components["fts"],
    )

    results = await injector._get_project_context(user_id=1)
    assert len(results) == 1
    assert "Good project" in results[0]["content"]
