"""
Tests for the briefing generator modules.

Tests each generator in isolation with mocked dependencies.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.scheduler.briefings import (
    BriefingGenerator,
    MorningBriefingGenerator,
    AfternoonFocusGenerator,
    EveningCheckinGenerator,
    MonthlyRetrospectiveGenerator,
)


class TestBriefingGeneratorBase:
    """Tests for the BriefingGenerator base class."""

    def test_base_class_is_abstract(self):
        """Base class cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BriefingGenerator(user_id=123)

    def test_format_date_header(self):
        """Date header is formatted correctly."""
        class ConcreteGenerator(BriefingGenerator):
            async def generate(self) -> str:
                return self._format_date_header()

        gen = ConcreteGenerator(user_id=123)
        header = asyncio.run(gen.generate())
        assert len(header) > 0
        assert "," in header  # e.g. "Sunday, 01 March"

    @pytest.mark.asyncio
    async def test_get_active_goals_with_no_store(self):
        """Returns empty list when goal_store is None."""
        class ConcreteGenerator(BriefingGenerator):
            async def generate(self) -> str:
                goals = await self._get_active_goals()
                return str(len(goals))

        gen = ConcreteGenerator(user_id=123, goal_store=None)
        result = await gen.generate()
        assert result == "0"

    @pytest.mark.asyncio
    async def test_get_active_goals_with_store(self):
        """Returns goals from the store."""
        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Goal 1", "description": "Desc 1"},
            {"id": 2, "title": "Goal 2", "description": None},
        ]

        class ConcreteGenerator(BriefingGenerator):
            async def generate(self) -> str:
                goals = await self._get_active_goals(limit=5)
                return str(len(goals))

        gen = ConcreteGenerator(user_id=123, goal_store=mock_store)
        result = await gen.generate()
        assert result == "2"
        mock_store.get_active.assert_called_once_with(123, limit=5)

    @pytest.mark.asyncio
    async def test_get_stale_goals_filters_by_date(self):
        """Only returns goals not updated within threshold."""
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=5)).isoformat()
        recent_date = (now - timedelta(days=1)).isoformat()

        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Old Goal", "updated_at": old_date},
            {"id": 2, "title": "Recent Goal", "updated_at": recent_date},
        ]

        class ConcreteGenerator(BriefingGenerator):
            async def generate(self) -> str:
                stale = await self._get_stale_goals(days=3)
                return ",".join(g["title"] for g in stale)

        gen = ConcreteGenerator(user_id=123, goal_store=mock_store)
        result = await gen.generate()
        assert "Old Goal" in result
        assert "Recent Goal" not in result


class TestMorningBriefingGenerator:
    """Tests for MorningBriefingGenerator."""

    @pytest.mark.asyncio
    async def test_generate_with_no_dependencies(self):
        """Generates basic briefing with no dependencies configured."""
        gen = MorningBriefingGenerator(user_id=123)
        content = await gen.generate()

        assert "Good morning" in content
        assert "no active goals" in content.lower()

    @pytest.mark.asyncio
    async def test_generate_with_goals(self):
        """Includes goals section when goals exist."""
        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Build Remy", "description": "Personal AI assistant"},
            {"id": 2, "title": "Learn Rust", "description": None},
        ]

        gen = MorningBriefingGenerator(user_id=123, goal_store=mock_store)
        content = await gen.generate()

        assert "Build Remy" in content
        assert "Personal AI assistant" in content
        assert "Learn Rust" in content
        assert "Make it count today" in content

    @pytest.mark.asyncio
    async def test_generate_with_calendar(self):
        """Includes calendar section when calendar client is configured."""
        mock_calendar = AsyncMock()
        mock_calendar.list_events.return_value = [
            {"summary": "Team standup", "start": "09:00"},
            {"summary": "Lunch with Alex", "start": "12:30"},
        ]
        # format_event is a sync method, not async
        mock_calendar.format_event = lambda e: f"• {e['summary']} at {e['start']}"

        gen = MorningBriefingGenerator(user_id=123, calendar=mock_calendar)
        content = await gen.generate()

        assert "Today's calendar" in content
        assert "Team standup" in content
        assert "Lunch with Alex" in content

    @pytest.mark.asyncio
    async def test_generate_with_empty_calendar(self):
        """Shows 'Nothing scheduled' when no events."""
        mock_calendar = AsyncMock()
        mock_calendar.list_events.return_value = []

        gen = MorningBriefingGenerator(user_id=123, calendar=mock_calendar)
        content = await gen.generate()

        assert "Nothing scheduled" in content

    @pytest.mark.asyncio
    async def test_generate_with_projects(self):
        """Includes projects section from fact store."""
        mock_facts = AsyncMock()
        mock_facts.get_by_category.return_value = [
            {"content": "remy - personal AI agent"},
            {"content": "blog - tech writing"},
        ]

        gen = MorningBriefingGenerator(user_id=123, fact_store=mock_facts)
        content = await gen.generate()

        assert "Tracked projects" in content
        assert "remy" in content
        mock_facts.get_by_category.assert_called_once_with(123, "project")

    @pytest.mark.asyncio
    async def test_generate_with_stale_plans(self):
        """Includes stale plan steps section."""
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=10)).isoformat()

        mock_plans = AsyncMock()
        mock_plans.stale_steps.return_value = [
            {
                "plan_title": "Car service",
                "step_title": "Book appointment",
                "step_updated_at": old_date,
                "last_attempt_outcome": "no answer",
            }
        ]

        gen = MorningBriefingGenerator(user_id=123, plan_store=mock_plans)
        content = await gen.generate()

        assert "Plans needing attention" in content
        assert "Car service" in content
        assert "Book appointment" in content

    def test_downloads_section_with_old_files(self, tmp_path, monkeypatch):
        """Detects old files in ~/Downloads."""
        downloads = tmp_path / "Downloads"
        downloads.mkdir()

        old_file = downloads / "old_report.pdf"
        old_file.write_text("x")
        os.utime(old_file, (old_file.stat().st_atime, old_file.stat().st_mtime - 10 * 86400))

        recent_file = downloads / "recent.txt"
        recent_file.write_text("y")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        gen = MorningBriefingGenerator(user_id=123)
        content = asyncio.run(gen._build_downloads_section())

        assert "old_report.pdf" in content
        assert "recent.txt" not in content
        assert "Downloads cleanup" in content

    def test_downloads_section_empty_when_no_old_files(self, tmp_path, monkeypatch):
        """Returns empty when no old files."""
        downloads = tmp_path / "Downloads"
        downloads.mkdir()

        recent_file = downloads / "recent.txt"
        recent_file.write_text("y")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        gen = MorningBriefingGenerator(user_id=123)
        content = asyncio.run(gen._build_downloads_section())

        assert content == ""


class TestAfternoonFocusGenerator:
    """Tests for AfternoonFocusGenerator."""

    @pytest.mark.asyncio
    async def test_generate_with_no_goals(self):
        """Shows encouragement to set goals when none exist."""
        mock_store = AsyncMock()
        mock_store.get_active.return_value = []

        gen = AfternoonFocusGenerator(user_id=123, goal_store=mock_store)
        content = await gen.generate()

        assert "Afternoon focus" in content
        assert "haven't set any goals" in content
        assert "you've got this" in content.lower()

    @pytest.mark.asyncio
    async def test_generate_with_goals(self):
        """Shows top priority goal."""
        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Ship feature X"},
            {"id": 2, "title": "Review PRs"},
        ]

        gen = AfternoonFocusGenerator(user_id=123, goal_store=mock_store)
        content = await gen.generate()

        assert "Ship feature X" in content
        assert "top priority" in content.lower()
        assert "Review PRs" not in content  # Only shows top goal

    @pytest.mark.asyncio
    async def test_generate_with_calendar(self):
        """Includes remaining calendar events."""
        mock_store = AsyncMock()
        mock_store.get_active.return_value = [{"id": 1, "title": "Focus work"}]

        mock_calendar = AsyncMock()
        mock_calendar.list_events.return_value = [
            {"summary": "Team sync", "start": "15:00"},
        ]
        # format_event is a sync method, not async
        mock_calendar.format_event = lambda e: f"• {e['summary']} at {e['start']}"

        gen = AfternoonFocusGenerator(
            user_id=123, goal_store=mock_store, calendar=mock_calendar
        )
        content = await gen.generate()

        assert "Still on today's schedule" in content
        assert "Team sync" in content


class TestEveningCheckinGenerator:
    """Tests for EveningCheckinGenerator."""

    @pytest.mark.asyncio
    async def test_generate_with_no_stale_goals(self):
        """Returns empty when no stale goals."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=1)).isoformat()

        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Active Goal", "updated_at": recent},
        ]

        gen = EveningCheckinGenerator(user_id=123, goal_store=mock_store)
        content = await gen.generate()

        assert content == ""

    @pytest.mark.asyncio
    async def test_generate_with_stale_goals(self):
        """Lists stale goals."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=5)).isoformat()

        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Forgotten Goal", "updated_at": old},
        ]

        gen = EveningCheckinGenerator(user_id=123, goal_store=mock_store)
        content = await gen.generate()

        assert "Evening check-in" in content
        assert "Forgotten Goal" in content
        assert "haven't mentioned" in content.lower()

    @pytest.mark.asyncio
    async def test_custom_stale_days_threshold(self):
        """Respects custom stale_days parameter."""
        now = datetime.now(timezone.utc)
        five_days_ago = (now - timedelta(days=5)).isoformat()

        mock_store = AsyncMock()
        mock_store.get_active.return_value = [
            {"id": 1, "title": "Goal", "updated_at": five_days_ago},
        ]

        # With 7-day threshold, goal is not stale
        gen = EveningCheckinGenerator(user_id=123, goal_store=mock_store, stale_days=7)
        content = await gen.generate()
        assert content == ""

        # With 3-day threshold, goal is stale
        gen = EveningCheckinGenerator(user_id=123, goal_store=mock_store, stale_days=3)
        content = await gen.generate()
        assert "Goal" in content


class TestMonthlyRetrospectiveGenerator:
    """Tests for MonthlyRetrospectiveGenerator."""

    @pytest.mark.asyncio
    async def test_generate_without_dependencies(self):
        """Returns empty when dependencies not configured."""
        gen = MonthlyRetrospectiveGenerator(user_id=123)
        content = await gen.generate()
        assert content == ""

    @pytest.mark.asyncio
    async def test_generate_without_claude(self):
        """Returns empty when Claude not configured."""
        mock_analyzer = AsyncMock()
        gen = MonthlyRetrospectiveGenerator(
            user_id=123, conversation_analyzer=mock_analyzer, claude=None
        )
        content = await gen.generate()
        assert content == ""

    @pytest.mark.asyncio
    async def test_generate_with_dependencies(self):
        """Generates retrospective using analyzer."""
        mock_analyzer = AsyncMock()
        mock_analyzer.generate_retrospective.return_value = (
            "## Monthly Retrospective\n\nGreat progress this month!"
        )
        mock_claude = MagicMock()

        gen = MonthlyRetrospectiveGenerator(
            user_id=123, conversation_analyzer=mock_analyzer, claude=mock_claude
        )
        content = await gen.generate()

        assert "Monthly Retrospective" in content
        assert "Great progress" in content
        mock_analyzer.generate_retrospective.assert_called_once_with(
            123, "month", mock_claude
        )

    @pytest.mark.asyncio
    async def test_truncates_long_retrospective(self):
        """Truncates content over 4000 characters."""
        mock_analyzer = AsyncMock()
        mock_analyzer.generate_retrospective.return_value = "x" * 5000
        mock_claude = MagicMock()

        gen = MonthlyRetrospectiveGenerator(
            user_id=123, conversation_analyzer=mock_analyzer, claude=mock_claude
        )
        content = await gen.generate()

        assert len(content) <= 4001  # 4000 + "…"
        assert content.endswith("…")

    @pytest.mark.asyncio
    async def test_handles_analyzer_error(self):
        """Returns empty on analyzer error."""
        mock_analyzer = AsyncMock()
        mock_analyzer.generate_retrospective.side_effect = Exception("API error")
        mock_claude = MagicMock()

        gen = MonthlyRetrospectiveGenerator(
            user_id=123, conversation_analyzer=mock_analyzer, claude=mock_claude
        )
        content = await gen.generate()

        assert content == ""
