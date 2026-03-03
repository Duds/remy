"""
Tests for concurrency control utilities.
"""

import asyncio
import pytest

from remy.utils.concurrency import (
    BoundedTaskRunner,
    PerUserTaskRunner,
    get_extraction_runner,
    get_per_user_extraction_runner,
)


class TestBoundedTaskRunner:
    """Test bounded task execution."""

    @pytest.mark.asyncio
    async def test_run_executes_coroutine(self):
        """run() executes and returns coroutine result."""
        runner = BoundedTaskRunner(max_concurrent=5)
        
        async def task():
            return "result"
        
        result = await runner.run(task())
        assert result == "result"

    @pytest.mark.asyncio
    async def test_run_limits_concurrency(self):
        """run() limits concurrent executions."""
        runner = BoundedTaskRunner(max_concurrent=2)
        max_concurrent_seen = 0
        
        async def task():
            nonlocal max_concurrent_seen
            max_concurrent_seen = max(max_concurrent_seen, runner.active_count)
            await asyncio.sleep(0.1)
            return "done"
        
        # Run 5 tasks with max 2 concurrent
        tasks = [runner.run(task()) for _ in range(5)]
        await asyncio.gather(*tasks)
        
        # Should never exceed 2 concurrent
        assert max_concurrent_seen <= 2

    @pytest.mark.asyncio
    async def test_run_background_returns_task(self):
        """run_background() returns a task handle."""
        runner = BoundedTaskRunner(max_concurrent=5)
        
        async def task():
            return "result"
        
        task_handle = runner.run_background(task())
        assert isinstance(task_handle, asyncio.Task)
        
        result = await task_handle
        assert result == "result"

    @pytest.mark.asyncio
    async def test_run_background_handles_exceptions(self):
        """run_background() logs but doesn't raise exceptions."""
        runner = BoundedTaskRunner(max_concurrent=5, name="test")
        
        async def failing_task():
            raise ValueError("boom")
        
        task_handle = runner.run_background(failing_task())
        result = await task_handle
        
        # Should return None on failure, not raise
        assert result is None

    @pytest.mark.asyncio
    async def test_active_count_tracks_running_tasks(self):
        """active_count reflects currently running tasks."""
        runner = BoundedTaskRunner(max_concurrent=5)
        
        assert runner.active_count == 0
        
        async def slow_task():
            await asyncio.sleep(0.5)
            return "done"
        
        task = runner.run_background(slow_task())
        await asyncio.sleep(0.1)  # Let task start
        
        assert runner.active_count == 1
        
        await task
        assert runner.active_count == 0


class TestPerUserTaskRunner:
    """Test per-user task management with cancellation."""

    @pytest.mark.asyncio
    async def test_run_for_user_executes_task(self):
        """run_for_user() executes the task."""
        runner = PerUserTaskRunner(max_concurrent=5)
        
        async def task():
            return "result"
        
        task_handle = runner.run_for_user(user_id=123, coro=task())
        result = await task_handle
        assert result == "result"

    @pytest.mark.asyncio
    async def test_run_for_user_cancels_existing(self):
        """run_for_user() cancels existing task for same user."""
        runner = PerUserTaskRunner(max_concurrent=5)
        cancelled = False
        
        async def long_task():
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
                return "first"
            except asyncio.CancelledError:
                cancelled = True
                raise
        
        async def quick_task():
            return "second"
        
        # Start first task
        runner.run_for_user(user_id=123, coro=long_task())
        await asyncio.sleep(0.1)  # Let it start
        
        # Start second task for same user
        second = runner.run_for_user(user_id=123, coro=quick_task())
        
        result = await second
        assert result == "second"
        assert cancelled  # First task was cancelled

    @pytest.mark.asyncio
    async def test_run_for_user_no_cancel_different_users(self):
        """run_for_user() doesn't cancel tasks for different users."""
        runner = PerUserTaskRunner(max_concurrent=5)
        
        async def task(name):
            await asyncio.sleep(0.1)
            return name
        
        # Start tasks for different users
        task1 = runner.run_for_user(user_id=123, coro=task("user1"))
        task2 = runner.run_for_user(user_id=456, coro=task("user2"))
        
        results = await asyncio.gather(task1, task2)
        assert set(results) == {"user1", "user2"}

    @pytest.mark.asyncio
    async def test_cancel_for_user(self):
        """cancel_for_user() cancels running task."""
        runner = PerUserTaskRunner(max_concurrent=5)
        
        async def long_task():
            await asyncio.sleep(10)
            return "done"
        
        runner.run_for_user(user_id=123, coro=long_task())
        await asyncio.sleep(0.1)  # Let it start
        
        result = runner.cancel_for_user(123)
        assert result is True


class TestGlobalRunners:
    """Test global runner singletons."""

    def test_get_extraction_runner_returns_singleton(self):
        """get_extraction_runner() returns same instance."""
        runner1 = get_extraction_runner()
        runner2 = get_extraction_runner()
        assert runner1 is runner2

    def test_get_per_user_extraction_runner_returns_singleton(self):
        """get_per_user_extraction_runner() returns same instance."""
        runner1 = get_per_user_extraction_runner()
        runner2 = get_per_user_extraction_runner()
        assert runner1 is runner2
