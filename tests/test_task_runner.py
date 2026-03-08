"""Tests for the sub-agent task runner and orchestration system (SAD v10 §11)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.agents.runner import TaskRunner, _make_worker
from remy.skills.loader import load_skill, load_skills


# ── Skills loader tests ───────────────────────────────────────────────────────


def test_load_skill_returns_empty_for_missing_skill(tmp_path):
    """load_skill returns empty string when no skill file exists."""
    with patch("remy.skills.loader.SKILLS_DIR", tmp_path):
        result = load_skill("nonexistent-skill")
    assert result == ""


def test_load_skill_returns_base_content(tmp_path):
    """load_skill returns base file content."""
    (tmp_path / "research.md").write_text("# Research Skill\nDo research.", encoding="utf-8")
    with patch("remy.skills.loader.SKILLS_DIR", tmp_path):
        result = load_skill("research")
    assert "Research Skill" in result


def test_load_skill_appends_local_override(tmp_path):
    """load_skill appends local override after base content."""
    (tmp_path / "research.md").write_text("Base content.", encoding="utf-8")
    (tmp_path / "research.local.md").write_text("Local override.", encoding="utf-8")
    with patch("remy.skills.loader.SKILLS_DIR", tmp_path):
        result = load_skill("research")
    assert "Base content." in result
    assert "Local override." in result
    # Local appears after base
    assert result.index("Base content.") < result.index("Local override.")


def test_load_skills_concatenates_with_separator(tmp_path):
    """load_skills merges multiple skills with a horizontal rule separator."""
    (tmp_path / "research.md").write_text("Research skill.", encoding="utf-8")
    (tmp_path / "email-triage.md").write_text("Email skill.", encoding="utf-8")
    with patch("remy.skills.loader.SKILLS_DIR", tmp_path):
        result = load_skills(["research", "email-triage"])
    assert "Research skill." in result
    assert "Email skill." in result
    assert "---" in result


def test_load_skills_skips_missing(tmp_path):
    """load_skills skips missing skills without raising."""
    (tmp_path / "research.md").write_text("Research.", encoding="utf-8")
    with patch("remy.skills.loader.SKILLS_DIR", tmp_path):
        result = load_skills(["research", "missing-skill"])
    assert "Research." in result


def test_load_skill_empty_name_returns_empty():
    """load_skill with empty name returns empty string."""
    assert load_skill("") == ""


# ── TaskRunner tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_runner_spawn_persists_to_db(tmp_path):
    """spawn() creates an agent_tasks row with status=pending then running."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    runner = TaskRunner(db=db)

    # Mock the worker and skill loader so no external APIs are called
    with patch("remy.agents.runner._make_worker") as mock_make:
        mock_worker = MagicMock()
        mock_worker.run = AsyncMock(return_value='{"summary": "done"}')
        mock_make.return_value = mock_worker
        with patch("remy.skills.loader.SKILLS_DIR"):
            task_id = await runner.spawn(
                worker_type="research",
                task_context={"topic": "test topic"},
            )

        # Let the asyncio task complete
        await asyncio.sleep(0.1)

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT task_id, worker_type, status FROM agent_tasks WHERE task_id=?",
            (task_id,),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == task_id
    assert row[1] == "research"
    assert row[2] == "done"


@pytest.mark.asyncio
async def test_task_runner_rejects_at_max_depth(tmp_path):
    """spawn() raises ValueError when depth >= max_depth (default 2)."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    runner = TaskRunner(db=db)
    # Default max_depth is 2; passing depth=2 should trigger the guard
    with pytest.raises(ValueError, match="max_depth"):
        await runner.spawn(
            worker_type="research",
            task_context={"topic": "x"},
            depth=2,
        )


@pytest.mark.asyncio
async def test_task_runner_rejects_at_max_workers(tmp_path):
    """spawn() raises ValueError when active worker count >= max_workers."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    runner = TaskRunner(db=db)
    # Fill the active pool with mock tasks
    for i in range(runner.max_workers):
        runner._active[f"fake-{i}"] = MagicMock()

    with pytest.raises(ValueError, match="pool full"):
        await runner.spawn(worker_type="research", task_context={"topic": "x"})


@pytest.mark.asyncio
async def test_task_runner_marks_failed_on_worker_error(tmp_path):
    """When the worker raises, the task is marked failed with the error message."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    runner = TaskRunner(db=db)

    with patch("remy.agents.runner._make_worker") as mock_make:
        mock_worker = MagicMock()
        mock_worker.run = AsyncMock(side_effect=RuntimeError("boom"))
        mock_make.return_value = mock_worker
        with patch("remy.skills.loader.SKILLS_DIR"):
            task_id = await runner.spawn(
                worker_type="research",
                task_context={"topic": "fail"},
            )
        await asyncio.sleep(0.1)

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT status, error FROM agent_tasks WHERE task_id=?", (task_id,)
        )
        row = await cursor.fetchone()

    assert row[0] == "failed"
    assert "boom" in row[1]


@pytest.mark.asyncio
async def test_check_stalled_marks_old_running_tasks(tmp_path):
    """check_stalled() marks tasks running beyond the stall threshold as stalled."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    runner = TaskRunner(db=db)

    # Insert a 'running' task with started_at 60 minutes ago
    import uuid

    task_id = str(uuid.uuid4())
    async with db.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO agent_tasks
                (task_id, worker_type, status, task_context, depth, created_at, started_at)
            VALUES (?, 'research', 'running', '{}', 0, datetime('now', '-61 minutes'),
                    datetime('now', '-61 minutes'))
            """,
            (task_id,),
        )
        await conn.commit()

    # Default stall_minutes is 30; task was inserted 61 minutes ago — should be stalled
    stalled = await runner.check_stalled()

    assert task_id in stalled

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT status FROM agent_tasks WHERE task_id=?", (task_id,)
        )
        row = await cursor.fetchone()
    assert row[0] == "stalled"


# ── _make_worker factory tests ────────────────────────────────────────────────


def test_make_worker_returns_research_agent():
    from remy.agents.workers.research import ResearchAgent

    worker = _make_worker("research", db=MagicMock(), runner=MagicMock())
    assert isinstance(worker, ResearchAgent)


def test_make_worker_returns_goal_worker():
    from remy.agents.workers.goal import GoalWorker

    worker = _make_worker("goal", db=MagicMock(), runner=MagicMock())
    assert isinstance(worker, GoalWorker)


def test_make_worker_returns_code_agent():
    from remy.agents.workers.code import CodeAgent

    worker = _make_worker("code", db=MagicMock(), runner=MagicMock())
    assert isinstance(worker, CodeAgent)


def test_make_worker_raises_for_unknown_type():
    with pytest.raises(ValueError, match="Unknown worker_type"):
        _make_worker("unknown", db=MagicMock(), runner=MagicMock())


# ── Database migration test ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_tasks_table_created(tmp_path):
    """DatabaseManager.init() creates the agent_tasks table."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_tasks'"
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == "agent_tasks"


@pytest.mark.asyncio
async def test_agent_tasks_index_created(tmp_path):
    """DatabaseManager.init() creates the status index on agent_tasks."""
    from remy.memory.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_agent_tasks_status'"
        )
        row = await cursor.fetchone()

    assert row is not None


# ── Heartbeat integration test ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_job_marks_agent_tasks_surfaced(tmp_path):
    """run_heartbeat_job marks unsurfaced done/failed tasks as surfaced_to_remy=1."""
    import uuid

    from remy.memory.database import DatabaseManager
    from remy.scheduler.heartbeat import run_heartbeat_job

    db = DatabaseManager(db_path=str(tmp_path / "remy.db"))
    await db.init()

    # Insert an unsurfaced done task
    task_id = str(uuid.uuid4())
    async with db.get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO agent_tasks
                (task_id, worker_type, status, task_context, depth,
                 created_at, synthesis, surfaced_to_remy)
            VALUES (?, 'research', 'done', '{}', 0, datetime('now'),
                    '{"summary": "done result"}', 0)
            """,
            (task_id,),
        )
        await conn.commit()

    with patch("remy.scheduler.heartbeat._in_quiet_hours", return_value=False):
        with patch("remy.scheduler.heartbeat.load_heartbeat_config", return_value="# Config"):
            result_mock = MagicMock()
            result_mock.outcome = "HEARTBEAT_OK"
            result_mock.items_checked = {}
            result_mock.items_surfaced = {}
            result_mock.model = ""
            result_mock.tokens_used = 0
            result_mock.duration_ms = 10

            handler = MagicMock()
            handler.run = AsyncMock(return_value=result_mock)

            await run_heartbeat_job(
                handler=handler,
                db=db,
                get_primary_chat_id=lambda: 12345,
                get_primary_user_id=lambda: 1,
            )

    # Verify the task was marked as surfaced
    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT surfaced_to_remy FROM agent_tasks WHERE task_id=?", (task_id,)
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == 1
