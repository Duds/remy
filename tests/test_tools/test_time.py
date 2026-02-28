"""Tests for remy.ai.tools.time module."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from remy.ai.tools.time import exec_get_current_time


class TestExecGetCurrentTime:
    """Tests for exec_get_current_time executor."""

    def test_returns_string(self):
        """Result should be a string."""
        registry = MagicMock()
        result = exec_get_current_time(registry)
        assert isinstance(result, str)

    def test_contains_timezone_info(self):
        """Result should mention Australia/Canberra timezone."""
        registry = MagicMock()
        result = exec_get_current_time(registry)
        assert "Australia/Canberra" in result

    def test_contains_date_label(self):
        """Result should contain 'Date:' label."""
        registry = MagicMock()
        result = exec_get_current_time(registry)
        assert "Date:" in result

    def test_contains_time_label(self):
        """Result should contain 'Time:' label."""
        registry = MagicMock()
        result = exec_get_current_time(registry)
        assert "Time:" in result

    def test_contains_iso_label(self):
        """Result should contain 'ISO:' label."""
        registry = MagicMock()
        result = exec_get_current_time(registry)
        assert "ISO:" in result

    def test_contains_24h_format(self):
        """Result should include 24-hour time format."""
        registry = MagicMock()
        result = exec_get_current_time(registry)
        assert "24h" in result

    @patch("remy.ai.tools.time.datetime")
    def test_uses_correct_timezone(self, mock_datetime):
        """Should use Australia/Canberra timezone."""
        import zoneinfo
        
        tz = zoneinfo.ZoneInfo("Australia/Canberra")
        fixed_time = datetime(2026, 3, 1, 14, 30, 0, tzinfo=tz)
        mock_datetime.now.return_value = fixed_time
        
        registry = MagicMock()
        result = exec_get_current_time(registry)
        
        mock_datetime.now.assert_called_once()
        call_args = mock_datetime.now.call_args
        assert call_args[0][0].key == "Australia/Canberra"

    def test_does_not_use_registry(self):
        """Registry is passed but not used (future-proofing)."""
        registry = MagicMock()
        exec_get_current_time(registry)
        assert not registry.method_calls
