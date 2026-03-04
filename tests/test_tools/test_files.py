"""Tests for remy.ai.tools.files module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.ai.tools.files import (
    exec_append_file,
    exec_clean_directory,
    exec_find_files,
    exec_get_file_download_link,
    exec_index_status,
    exec_list_directory,
    exec_organize_directory,
    exec_read_file,
    exec_scan_downloads,
    exec_search_files,
    exec_write_file,
)


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._file_indexer = kwargs.get("file_indexer")
    registry._claude_client = kwargs.get("claude_client")
    return registry


class TestExecReadFile:
    """Tests for exec_read_file executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a file path."""
        registry = make_registry()
        result = await exec_read_file(registry, {"path": ""})
        assert "provide" in result.lower() or "path" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        result = await exec_read_file(registry, {"path": "/nonexistent/file.txt"})
        assert isinstance(result, str)


class TestExecGetFileDownloadLink:
    """Tests for exec_get_file_download_link executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a file path."""
        registry = make_registry()
        result = await exec_get_file_download_link(registry, {"path": ""})
        assert "provide" in result.lower() or "path" in result.lower()

    @pytest.mark.asyncio
    @patch("remy.ai.tools.files.settings")
    async def test_disabled_when_base_url_unset(self, mock_settings):
        """Should return disabled message when FILE_LINK_BASE_URL is not set."""
        # Patch only file_link so path sanitization still uses real allowed_base_dirs
        from remy.config import settings as real_settings

        mock_settings.file_link_base_url = ""
        mock_settings.file_link_secret = getattr(
            real_settings, "file_link_secret", None
        )
        mock_settings.health_api_token = getattr(
            real_settings, "health_api_token", None
        )
        mock_settings.file_link_expiry_minutes = getattr(
            real_settings, "file_link_expiry_minutes", 15
        )
        mock_settings.allowed_base_dirs = real_settings.allowed_base_dirs
        registry = make_registry()
        result = await exec_get_file_download_link(
            registry, {"path": "~/Documents/notes.md"}
        )
        assert isinstance(result, str)
        assert "FILE_LINK_BASE_URL" in result or "disabled" in result.lower()


class TestExecListDirectory:
    """Tests for exec_list_directory executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a directory path."""
        registry = make_registry()
        result = await exec_list_directory(registry, {"path": ""})
        assert "provide" in result.lower() or "path" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        result = await exec_list_directory(registry, {"path": "/nonexistent"})
        assert isinstance(result, str)


class TestExecWriteFile:
    """Tests for exec_write_file executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a file path."""
        registry = make_registry()
        result = await exec_write_file(registry, {"path": "", "content": "test"})
        assert "provide" in result.lower() or "path" in result.lower()


class TestExecAppendFile:
    """Tests for exec_append_file executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a file path."""
        registry = make_registry()
        result = await exec_append_file(registry, {"path": "", "content": "test"})
        assert "provide" in result.lower() or "path" in result.lower()


class TestExecFindFiles:
    """Tests for exec_find_files executor."""

    @pytest.mark.asyncio
    async def test_requires_pattern(self):
        """Should require a search pattern."""
        registry = make_registry()
        result = await exec_find_files(registry, {"pattern": ""})
        assert "provide" in result.lower() or "pattern" in result.lower()


class TestExecScanDownloads:
    """Tests for exec_scan_downloads executor."""

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result."""
        registry = make_registry()
        result = await exec_scan_downloads(registry)
        assert isinstance(result, str)


class TestExecOrganizeDirectory:
    """Tests for exec_organize_directory executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a directory path."""
        registry = make_registry()
        result = await exec_organize_directory(registry, {"path": ""})
        assert "provide" in result.lower() or "path" in result.lower()


class TestExecCleanDirectory:
    """Tests for exec_clean_directory executor."""

    @pytest.mark.asyncio
    async def test_requires_path(self):
        """Should require a directory path."""
        registry = make_registry()
        result = await exec_clean_directory(registry, {"path": ""})
        assert "provide" in result.lower() or "path" in result.lower()


class TestExecSearchFiles:
    """Tests for exec_search_files executor."""

    @pytest.mark.asyncio
    async def test_no_indexer_returns_not_available(self):
        """Should return not available when file indexer not configured."""
        registry = make_registry(file_indexer=None)
        result = await exec_search_files(registry, {"query": "test"})
        assert "not available" in result.lower() or "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_query(self):
        """Should require a search query."""
        indexer = AsyncMock()
        registry = make_registry(file_indexer=indexer)

        result = await exec_search_files(registry, {"query": ""})
        assert "provide" in result.lower() or "query" in result.lower()


class TestExecIndexStatus:
    """Tests for exec_index_status executor."""

    @pytest.mark.asyncio
    async def test_no_indexer_returns_not_available(self):
        """Should return not available when file indexer not configured."""
        registry = make_registry(file_indexer=None)
        result = await exec_index_status(registry)
        assert "not available" in result.lower() or "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_string_result(self):
        """Should return a string result when indexer configured."""
        indexer = MagicMock()
        indexer.extensions = [".txt", ".py"]
        indexer.index_path = "/tmp/index"
        registry = make_registry(file_indexer=indexer)

        result = await exec_index_status(registry)
        assert isinstance(result, str)
