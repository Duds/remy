"""
Concurrency control utilities for bounded parallelism.

Provides semaphore-based limiting for background tasks to prevent:
- API rate limit exhaustion under burst load
- Uncontrolled token spend from parallel extractions
- Resource exhaustion from unbounded task spawning
"""

import asyncio
import logging
from typing import Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BoundedTaskRunner:
    """
    Runs async tasks with bounded concurrency using a semaphore.
    
    Usage:
        runner = BoundedTaskRunner(max_concurrent=5)
        await runner.run(some_async_function())
        
        # Or fire-and-forget with background task
        runner.run_background(some_async_function())
    """
    
    def __init__(self, max_concurrent: int = 5, name: str = "default") -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._name = name
        self._active_count = 0
        self._total_count = 0
    
    @property
    def active_count(self) -> int:
        """Number of currently running tasks."""
        return self._active_count
    
    @property
    def total_count(self) -> int:
        """Total number of tasks run since creation."""
        return self._total_count
    
    async def run(self, coro: Awaitable[T]) -> T:
        """Run a coroutine with bounded concurrency."""
        async with self._semaphore:
            self._active_count += 1
            self._total_count += 1
            try:
                return await coro
            finally:
                self._active_count -= 1
    
    def run_background(self, coro: Awaitable[T]) -> asyncio.Task[T | None]:
        """
        Run a coroutine in the background with bounded concurrency.
        
        Returns the task handle. Exceptions are logged but not raised.
        """
        async def _wrapped():
            try:
                return await self.run(coro)
            except asyncio.CancelledError:
                logger.debug("Background task cancelled in %s runner", self._name)
                return None
            except Exception as e:
                logger.warning(
                    "Background task failed in %s runner: %s",
                    self._name, e
                )
                return None
        
        return asyncio.create_task(_wrapped())


class PerUserTaskRunner:
    """
    Manages bounded tasks per user with cancellation support.
    
    When a new task is submitted for a user, any existing task for that
    user is cancelled. This prevents resource waste when users send
    multiple messages rapidly.
    """
    
    def __init__(self, max_concurrent: int = 5, name: str = "per_user") -> None:
        self._runner = BoundedTaskRunner(max_concurrent, name)
        self._user_tasks: dict[int, asyncio.Task] = {}
    
    def run_for_user(
        self,
        user_id: int,
        coro: Awaitable[T],
        cancel_existing: bool = True,
    ) -> asyncio.Task[T | None]:
        """
        Run a task for a specific user.
        
        If cancel_existing is True and there's already a task running
        for this user, it will be cancelled before starting the new one.
        """
        if cancel_existing and user_id in self._user_tasks:
            existing = self._user_tasks[user_id]
            if not existing.done():
                existing.cancel()
                logger.debug(
                    "Cancelled existing task for user %d",
                    user_id
                )
        
        task = self._runner.run_background(coro)
        self._user_tasks[user_id] = task
        
        # Clean up reference when task completes
        def _cleanup(t):
            if self._user_tasks.get(user_id) is t:
                del self._user_tasks[user_id]
        
        task.add_done_callback(_cleanup)
        return task
    
    def cancel_for_user(self, user_id: int) -> bool:
        """Cancel any running task for the given user."""
        task = self._user_tasks.get(user_id)
        if task and not task.done():
            task.cancel()
            return True
        return False
    
    @property
    def active_count(self) -> int:
        """Number of currently running tasks across all users."""
        return self._runner.active_count


# Global runners for common use cases
_extraction_runner: BoundedTaskRunner | None = None
_per_user_extraction_runner: PerUserTaskRunner | None = None


def get_extraction_runner() -> BoundedTaskRunner:
    """Get the global extraction runner (max 5 concurrent extractions)."""
    global _extraction_runner
    if _extraction_runner is None:
        _extraction_runner = BoundedTaskRunner(max_concurrent=5, name="extraction")
    return _extraction_runner


def get_per_user_extraction_runner() -> PerUserTaskRunner:
    """Get the per-user extraction runner with cancellation support."""
    global _per_user_extraction_runner
    if _per_user_extraction_runner is None:
        _per_user_extraction_runner = PerUserTaskRunner(max_concurrent=5, name="per_user_extraction")
    return _per_user_extraction_runner
