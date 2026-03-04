"""Tests for remy.ai.tools.plans module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remy.ai.tools.plans import (
    exec_create_plan,
    exec_get_plan,
    exec_list_plans,
    exec_update_plan,
    exec_update_plan_status,
    exec_update_plan_step,
)


USER_ID = 42


def make_registry(**kwargs) -> MagicMock:
    """Create a mock registry with sensible defaults."""
    registry = MagicMock()
    registry._plan_store = kwargs.get("plan_store")
    registry._goal_store = kwargs.get("goal_store")
    return registry


class TestExecCreatePlan:
    """Tests for exec_create_plan executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when plan store not configured."""
        registry = make_registry(plan_store=None)
        result = await exec_create_plan(registry, {"title": "Test"}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_title(self):
        """Should require a plan title."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_create_plan(
            registry, {"title": "", "steps": ["Step 1"]}, USER_ID
        )
        assert "provide" in result.lower() and "title" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_steps(self):
        """Should require at least one step."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_create_plan(
            registry, {"title": "My Plan", "steps": []}, USER_ID
        )
        assert "provide" in result.lower() and "step" in result.lower()

    @pytest.mark.asyncio
    async def test_creates_plan_successfully(self):
        """Should create plan and return confirmation."""
        store = AsyncMock()
        store.create_plan = AsyncMock(return_value=123)
        registry = make_registry(plan_store=store)

        result = await exec_create_plan(
            registry,
            {
                "title": "Learn Python",
                "description": "Master the language",
                "steps": ["Read docs", "Write code", "Build project"],
            },
            USER_ID,
        )

        store.create_plan.assert_called_once_with(
            42,
            "Learn Python",
            "Master the language",
            ["Read docs", "Write code", "Build project"],
            goal_id=None,
        )
        assert "123" in result or "created" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_create_plan_with_goal_id(self):
        """Should validate goal exists for user then pass goal_id to store."""
        store = AsyncMock()
        store.create_plan = AsyncMock(return_value=99)
        goal_store = AsyncMock()
        goal_store.exists_for_user = AsyncMock(return_value=True)
        registry = make_registry(plan_store=store, goal_store=goal_store)
        result = await exec_create_plan(
            registry,
            {
                "title": "Fix cupboard",
                "steps": ["Buy hinge", "Install"],
                "goal_id": 5,
            },
            USER_ID,
        )
        goal_store.exists_for_user.assert_called_once_with(USER_ID, 5)
        store.create_plan.assert_called_once_with(
            42,
            "Fix cupboard",
            None,
            ["Buy hinge", "Install"],
            goal_id=5,
        )
        assert "99" in result or "created" in result.lower()

    @pytest.mark.asyncio
    async def test_create_plan_with_goal_id_rejects_unknown_goal(self):
        """Should return error when goal_id does not exist or not owned by user."""
        store = AsyncMock()
        goal_store = AsyncMock()
        goal_store.exists_for_user = AsyncMock(return_value=False)
        registry = make_registry(plan_store=store, goal_store=goal_store)
        result = await exec_create_plan(
            registry,
            {
                "title": "Fix cupboard",
                "steps": ["Buy hinge"],
                "goal_id": 999,
            },
            USER_ID,
        )
        store.create_plan.assert_not_called()
        assert "not found" in result.lower() or "get_goals" in result.lower()

    @pytest.mark.asyncio
    async def test_includes_steps_in_response(self):
        """Should include steps in the response."""
        store = AsyncMock()
        store.create_plan = AsyncMock(return_value=1)
        registry = make_registry(plan_store=store)

        result = await exec_create_plan(
            registry,
            {
                "title": "Test Plan",
                "steps": ["Step A", "Step B"],
            },
            USER_ID,
        )

        assert "Step A" in result or "Step B" in result or "steps" in result.lower()


class TestExecGetPlan:
    """Tests for exec_get_plan executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when plan store not configured."""
        registry = make_registry(plan_store=None)
        result = await exec_get_plan(registry, {"plan_id": 1}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_plan_id_or_title(self):
        """Should require either plan_id or title."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_get_plan(registry, {}, USER_ID)
        assert "provide" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_plan_not_found(self):
        """Should return not found for nonexistent plan."""
        store = AsyncMock()
        store.get_plan = AsyncMock(return_value=None)
        registry = make_registry(plan_store=store)

        result = await exec_get_plan(registry, {"plan_id": 999}, USER_ID)
        assert "not found" in result.lower() or "no plan" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_plan_details(self):
        """Should return plan details with steps."""
        plan = {
            "id": 1,
            "title": "Learn Rust",
            "description": "Systems programming",
            "status": "active",
            "created_at": "2026-03-01T10:00:00",
            "updated_at": "2026-03-01T10:00:00",
            "steps": [
                {
                    "id": 1,
                    "position": 1,
                    "title": "Install Rust",
                    "status": "done",
                    "notes": None,
                    "attempts": [],
                },
                {
                    "id": 2,
                    "position": 2,
                    "title": "Read the book",
                    "status": "in_progress",
                    "notes": None,
                    "attempts": [],
                },
            ],
        }
        store = AsyncMock()
        store.get_plan = AsyncMock(return_value=plan)
        registry = make_registry(plan_store=store)

        result = await exec_get_plan(registry, {"plan_id": 1}, USER_ID)

        assert "Learn Rust" in result
        assert "Install Rust" in result or "Read the book" in result


class TestExecListPlans:
    """Tests for exec_list_plans executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when plan store not configured."""
        registry = make_registry(plan_store=None)
        result = await exec_list_plans(registry, {}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_no_plans_message(self):
        """Should return appropriate message when no plans."""
        store = AsyncMock()
        store.list_plans = AsyncMock(return_value=[])
        registry = make_registry(plan_store=store)

        result = await exec_list_plans(registry, {}, USER_ID)
        assert "no" in result.lower() and "plan" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_plan_list(self):
        """Should return formatted list of plans."""
        plans = [
            {
                "id": 1,
                "title": "Learn Python",
                "status": "active",
                "total_steps": 5,
                "step_counts": {"done": 2, "in_progress": 1, "pending": 2},
                "updated_at": "2026-03-01T10:00:00",
            },
            {
                "id": 2,
                "title": "Build App",
                "status": "active",
                "total_steps": 3,
                "step_counts": {"pending": 3},
                "updated_at": "2026-02-28T10:00:00",
            },
        ]
        store = AsyncMock()
        store.list_plans = AsyncMock(return_value=plans)
        registry = make_registry(plan_store=store)

        result = await exec_list_plans(registry, {}, USER_ID)

        assert "Learn Python" in result or "Build App" in result

    @pytest.mark.asyncio
    async def test_status_filter_respected(self):
        """Should respect the status filter."""
        store = AsyncMock()
        store.list_plans = AsyncMock(return_value=[])
        registry = make_registry(plan_store=store)

        await exec_list_plans(registry, {"status": "complete"}, USER_ID)

        store.list_plans.assert_called_once_with(USER_ID, "complete")


class TestExecUpdatePlanStep:
    """Tests for exec_update_plan_step executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when plan store not configured."""
        registry = make_registry(plan_store=None)
        result = await exec_update_plan_step(registry, {"step_id": 1}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_step_id(self):
        """Should require a step ID."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_step(registry, {}, USER_ID)
        assert "provide" in result.lower() and "step" in result.lower()

    @pytest.mark.asyncio
    async def test_updates_step_status(self):
        """Should update step status."""
        store = AsyncMock()
        store.update_step_status = AsyncMock(return_value=True)
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_step(
            registry,
            {
                "step_id": 1,
                "status": "done",
            },
            USER_ID,
        )

        store.update_step_status.assert_called_once_with(1, "done")
        assert "updated" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_logs_attempt(self):
        """Should log an attempt when provided."""
        store = AsyncMock()
        store.update_step_status = AsyncMock(return_value=True)
        store.add_attempt = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_step(
            registry,
            {
                "step_id": 1,
                "status": "in_progress",
                "attempt_outcome": "success",
                "attempt_notes": "Completed first draft",
            },
            USER_ID,
        )

        store.add_attempt.assert_called_once()
        assert "attempt" in result.lower() or "logged" in result.lower()


class TestExecUpdatePlanStatus:
    """Tests for exec_update_plan_status executor."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when plan store not configured."""
        registry = make_registry(plan_store=None)
        result = await exec_update_plan_status(registry, {"plan_id": 1}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_plan_id(self):
        """Should require a plan ID."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_status(
            registry, {"status": "complete"}, USER_ID
        )
        assert "provide" in result.lower() and "plan" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_status(self):
        """Should require a status."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_status(registry, {"plan_id": 1}, USER_ID)
        assert "provide" in result.lower() and "status" in result.lower()

    @pytest.mark.asyncio
    async def test_marks_plan_complete(self):
        """Should mark plan as complete."""
        store = AsyncMock()
        store.update_plan_status = AsyncMock(return_value=True)
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_status(
            registry,
            {
                "plan_id": 1,
                "status": "complete",
            },
            USER_ID,
        )

        store.update_plan_status.assert_called_once_with(1, "complete")
        assert "complete" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_returns_not_found(self):
        """Should return not found for nonexistent plan."""
        store = AsyncMock()
        store.update_plan_status = AsyncMock(return_value=False)
        registry = make_registry(plan_store=store)

        result = await exec_update_plan_status(
            registry,
            {
                "plan_id": 999,
                "status": "complete",
            },
            USER_ID,
        )

        assert "not found" in result.lower() or "no plan" in result.lower()


class TestExecUpdatePlan:
    """Tests for exec_update_plan executor (goal–plan link)."""

    @pytest.mark.asyncio
    async def test_no_store_returns_not_available(self):
        """Should return not available when plan store not configured."""
        registry = make_registry(plan_store=None)
        result = await exec_update_plan(registry, {"plan_id": 1}, USER_ID)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_plan_id(self):
        """Should require a plan ID."""
        store = AsyncMock()
        registry = make_registry(plan_store=store)
        result = await exec_update_plan(registry, {}, USER_ID)
        assert "provide" in result.lower() and "plan" in result.lower()

    @pytest.mark.asyncio
    async def test_links_plan_to_goal(self):
        """Should call update_plan_goal with goal_id."""
        store = AsyncMock()
        store.update_plan_goal = AsyncMock(return_value=True)
        registry = make_registry(plan_store=store)
        result = await exec_update_plan(
            registry, {"plan_id": 2, "goal_id": 10}, USER_ID
        )
        store.update_plan_goal.assert_called_once_with(2, USER_ID, 10)
        assert "linked" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_clears_goal_link(self):
        """Should clear goal when goal_id omitted."""
        store = AsyncMock()
        store.update_plan_goal = AsyncMock(return_value=True)
        registry = make_registry(plan_store=store)
        result = await exec_update_plan(registry, {"plan_id": 2}, USER_ID)
        store.update_plan_goal.assert_called_once_with(2, USER_ID, None)
        assert "cleared" in result.lower() or "✅" in result

    @pytest.mark.asyncio
    async def test_returns_not_found(self):
        """Should return not found when plan does not exist."""
        store = AsyncMock()
        store.update_plan_goal = AsyncMock(return_value=False)
        registry = make_registry(plan_store=store)
        result = await exec_update_plan(
            registry, {"plan_id": 999, "goal_id": 1}, USER_ID
        )
        assert "no plan" in result.lower() or "not found" in result.lower()
