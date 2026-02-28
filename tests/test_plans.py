"""Tests for plan tracking (PlanStore)."""

import pytest
import pytest_asyncio

from remy.memory.database import DatabaseManager
from remy.memory.plans import PlanStore


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    await db.init()
    # Create test users to satisfy foreign key constraints
    await db.upsert_user(123, "testuser", "Test", "User")
    await db.upsert_user(456, "otheruser", "Other", "User")
    yield db
    await db.close()


@pytest_asyncio.fixture
async def plan_store(db):
    """Create a PlanStore instance."""
    return PlanStore(db)


@pytest.mark.asyncio
async def test_create_plan_with_steps(plan_store):
    """Test creating a plan with initial steps."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Fix the fence",
        description="Repair the backyard fence",
        steps=["Get quotes", "Hire contractor", "Supervise work"],
    )

    assert plan_id > 0

    plan = await plan_store.get_plan(plan_id)
    assert plan is not None
    assert plan["title"] == "Fix the fence"
    assert plan["description"] == "Repair the backyard fence"
    assert plan["status"] == "active"
    assert len(plan["steps"]) == 3
    assert plan["steps"][0]["title"] == "Get quotes"
    assert plan["steps"][0]["status"] == "pending"
    assert plan["steps"][0]["position"] == 1
    assert plan["steps"][1]["position"] == 2
    assert plan["steps"][2]["position"] == 3


@pytest.mark.asyncio
async def test_create_plan_without_description(plan_store):
    """Test creating a plan without a description."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Quick task",
        steps=["Step 1"],
    )

    plan = await plan_store.get_plan(plan_id)
    assert plan["title"] == "Quick task"
    assert plan["description"] is None


@pytest.mark.asyncio
async def test_add_step_to_existing_plan(plan_store):
    """Test adding a step to an existing plan."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    step_id = await plan_store.add_step(plan_id, "Step 2", notes="Some notes")

    plan = await plan_store.get_plan(plan_id)
    assert len(plan["steps"]) == 2
    assert plan["steps"][1]["title"] == "Step 2"
    assert plan["steps"][1]["notes"] == "Some notes"
    assert plan["steps"][1]["position"] == 2


@pytest.mark.asyncio
async def test_update_step_status(plan_store):
    """Test updating step status."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    plan = await plan_store.get_plan(plan_id)
    step_id = plan["steps"][0]["id"]

    updated = await plan_store.update_step_status(step_id, "in_progress")
    assert updated is True

    plan = await plan_store.get_plan(plan_id)
    assert plan["steps"][0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_update_step_status_invalid(plan_store):
    """Test that invalid status raises ValueError."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    plan = await plan_store.get_plan(plan_id)
    step_id = plan["steps"][0]["id"]

    with pytest.raises(ValueError, match="Invalid status"):
        await plan_store.update_step_status(step_id, "invalid_status")


@pytest.mark.asyncio
async def test_add_attempt(plan_store):
    """Test logging an attempt on a step."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Call mechanic"],
    )

    plan = await plan_store.get_plan(plan_id)
    step_id = plan["steps"][0]["id"]

    attempt_id = await plan_store.add_attempt(step_id, "no answer", "Left voicemail")
    assert attempt_id > 0

    plan = await plan_store.get_plan(plan_id)
    assert len(plan["steps"][0]["attempts"]) == 1
    assert plan["steps"][0]["attempts"][0]["outcome"] == "no answer"
    assert plan["steps"][0]["attempts"][0]["notes"] == "Left voicemail"


@pytest.mark.asyncio
async def test_multiple_attempts(plan_store):
    """Test logging multiple attempts on a step."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Call mechanic"],
    )

    plan = await plan_store.get_plan(plan_id)
    step_id = plan["steps"][0]["id"]

    await plan_store.add_attempt(step_id, "no answer")
    await plan_store.add_attempt(step_id, "busy")
    await plan_store.add_attempt(step_id, "booked appointment")

    plan = await plan_store.get_plan(plan_id)
    assert len(plan["steps"][0]["attempts"]) == 3
    assert plan["steps"][0]["attempts"][0]["outcome"] == "no answer"
    assert plan["steps"][0]["attempts"][2]["outcome"] == "booked appointment"


@pytest.mark.asyncio
async def test_list_plans(plan_store):
    """Test listing plans for a user."""
    await plan_store.create_plan(user_id=123, title="Plan A", steps=["Step 1"])
    await plan_store.create_plan(user_id=123, title="Plan B", steps=["Step 1", "Step 2"])
    await plan_store.create_plan(user_id=456, title="Other user plan", steps=["Step 1"])

    plans = await plan_store.list_plans(user_id=123, status="active")
    assert len(plans) == 2
    assert {p["title"] for p in plans} == {"Plan A", "Plan B"}


@pytest.mark.asyncio
async def test_list_plans_with_step_counts(plan_store):
    """Test that list_plans includes step progress counts."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1", "Step 2", "Step 3"],
    )

    plan = await plan_store.get_plan(plan_id)
    await plan_store.update_step_status(plan["steps"][0]["id"], "done")
    await plan_store.update_step_status(plan["steps"][1]["id"], "in_progress")

    plans = await plan_store.list_plans(user_id=123)
    assert len(plans) == 1
    assert plans[0]["step_counts"]["done"] == 1
    assert plans[0]["step_counts"]["in_progress"] == 1
    assert plans[0]["step_counts"]["pending"] == 1
    assert plans[0]["total_steps"] == 3


@pytest.mark.asyncio
async def test_update_plan_status(plan_store):
    """Test marking a plan as complete."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    updated = await plan_store.update_plan_status(plan_id, "complete")
    assert updated is True

    plan = await plan_store.get_plan(plan_id)
    assert plan["status"] == "complete"


@pytest.mark.asyncio
async def test_update_plan_status_abandoned(plan_store):
    """Test marking a plan as abandoned."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    await plan_store.update_plan_status(plan_id, "abandoned")

    plan = await plan_store.get_plan(plan_id)
    assert plan["status"] == "abandoned"


@pytest.mark.asyncio
async def test_update_plan_status_invalid(plan_store):
    """Test that invalid plan status raises ValueError."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    with pytest.raises(ValueError, match="Invalid status"):
        await plan_store.update_plan_status(plan_id, "invalid")


@pytest.mark.asyncio
async def test_get_plan_by_title(plan_store):
    """Test finding a plan by fuzzy title match."""
    await plan_store.create_plan(
        user_id=123,
        title="Fix the backyard fence",
        steps=["Step 1"],
    )

    plan = await plan_store.get_plan_by_title(user_id=123, title="fence")
    assert plan is not None
    assert plan["title"] == "Fix the backyard fence"


@pytest.mark.asyncio
async def test_get_plan_by_title_not_found(plan_store):
    """Test that get_plan_by_title returns None when not found."""
    await plan_store.create_plan(
        user_id=123,
        title="Fix the fence",
        steps=["Step 1"],
    )

    plan = await plan_store.get_plan_by_title(user_id=123, title="nonexistent")
    assert plan is None


@pytest.mark.asyncio
async def test_stale_steps(plan_store, db):
    """Test finding stale steps."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1", "Step 2"],
    )

    # Manually backdate the steps to simulate staleness
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE plan_steps SET updated_at = datetime('now', '-10 days') WHERE plan_id = ?",
            (plan_id,),
        )
        await conn.commit()

    stale = await plan_store.stale_steps(user_id=123, days=7)
    assert len(stale) == 2


@pytest.mark.asyncio
async def test_stale_steps_excludes_done(plan_store, db):
    """Test that stale_steps excludes completed steps."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1", "Step 2"],
    )

    plan = await plan_store.get_plan(plan_id)
    await plan_store.update_step_status(plan["steps"][0]["id"], "done")

    # Manually backdate the steps to simulate staleness
    async with db.get_connection() as conn:
        await conn.execute(
            "UPDATE plan_steps SET updated_at = datetime('now', '-10 days') WHERE plan_id = ?",
            (plan_id,),
        )
        await conn.commit()

    stale = await plan_store.stale_steps(user_id=123, days=7)
    assert len(stale) == 1
    assert stale[0]["step_title"] == "Step 2"


@pytest.mark.asyncio
async def test_stale_steps_excludes_inactive_plans(plan_store):
    """Test that stale_steps excludes steps from completed/abandoned plans."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    await plan_store.update_plan_status(plan_id, "complete")

    stale = await plan_store.stale_steps(user_id=123, days=0)
    assert len(stale) == 0


@pytest.mark.asyncio
async def test_delete_plan(plan_store):
    """Test deleting a plan."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    plan = await plan_store.get_plan(plan_id)
    await plan_store.add_attempt(plan["steps"][0]["id"], "test attempt")

    deleted = await plan_store.delete_plan(user_id=123, plan_id=plan_id)
    assert deleted is True

    plan = await plan_store.get_plan(plan_id)
    assert plan is None


@pytest.mark.asyncio
async def test_delete_plan_wrong_user(plan_store):
    """Test that deleting a plan fails for wrong user."""
    plan_id = await plan_store.create_plan(
        user_id=123,
        title="Test plan",
        steps=["Step 1"],
    )

    deleted = await plan_store.delete_plan(user_id=456, plan_id=plan_id)
    assert deleted is False

    plan = await plan_store.get_plan(plan_id)
    assert plan is not None


@pytest.mark.asyncio
async def test_list_plans_filter_by_status(plan_store):
    """Test filtering plans by status."""
    plan1 = await plan_store.create_plan(user_id=123, title="Active", steps=["S1"])
    plan2 = await plan_store.create_plan(user_id=123, title="Complete", steps=["S1"])
    await plan_store.update_plan_status(plan2, "complete")

    active = await plan_store.list_plans(user_id=123, status="active")
    assert len(active) == 1
    assert active[0]["title"] == "Active"

    complete = await plan_store.list_plans(user_id=123, status="complete")
    assert len(complete) == 1
    assert complete[0]["title"] == "Complete"

    all_plans = await plan_store.list_plans(user_id=123, status="all")
    assert len(all_plans) == 2
