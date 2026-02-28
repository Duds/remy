"""
Tests for MemoryInjector's project context extraction logic.
Verifies that README.md files are read correctly from tracked projects.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
