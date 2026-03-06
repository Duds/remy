"""Tests for run_claude_code tool (SAD v7 P2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from remy.ai.tools.claude_code import exec_run_claude_code


def make_registry() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_run_claude_code_requires_task():
    result = await exec_run_claude_code(make_registry(), {}, user_id=1)
    assert "task" in result.lower()
    assert "provide" in result.lower()


@pytest.mark.asyncio
async def test_run_claude_code_cli_not_found():
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await exec_run_claude_code(
            make_registry(),
            {"task": "Fix the bug in foo.py"},
            user_id=1,
        )
    assert "not found" in result.lower() or "claude" in result.lower()


@pytest.mark.asyncio
async def test_run_claude_code_success_returns_stdout_stderr_exit_code():
    from unittest.mock import AsyncMock

    async def fake_communicate(input=None):
        return (b"Done.", b"")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(side_effect=fake_communicate)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=None)

    async def fake_create_subprocess(*args, **kwargs):
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
        result = await exec_run_claude_code(
            make_registry(),
            {"task": "Add a test", "context": "file: bar.py"},
            user_id=1,
        )
    assert "Exit code: 0" in result
    assert "Done." in result
