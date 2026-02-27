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
        "fact_store": MagicMock(),
        "goal_store": MagicMock(),
        "fts": MagicMock(),
    }

@pytest.mark.asyncio
async def test_get_project_context_reads_readme(tmp_path, mock_components):
    # Setup: Create a fake project with a README
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    readme = project_dir / "README.md"
    readme.write_text("Hello from README", encoding="utf-8")
    
    # Mock FactStore to return this project
    fact_store = mock_components["fact_store"]
    fact_store.get_by_category = AsyncMock(return_value=[
        {"category": "project", "content": str(project_dir)}
    ])
    
    injector = MemoryInjector(
        mock_components["db"],
        mock_components["embeddings"],
        fact_store,
        mock_components["goal_store"],
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
    
    fact_store = mock_components["fact_store"]
    fact_store.get_by_category = AsyncMock(return_value=[
        {"category": "project", "content": str(project_dir)}
    ])
    
    injector = MemoryInjector(
        mock_components["db"],
        mock_components["embeddings"],
        fact_store,
        mock_components["goal_store"],
        mock_components["fts"]
    )
    
    # Execution
    results = await injector._get_project_context(user_id=1)
    
    # Assertions
    assert len(results) == 0
