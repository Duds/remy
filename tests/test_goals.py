"""
Tests for remy/memory/goals.py — GoalExtractor (mocked Claude) and GoalStore.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from remy.memory.database import DatabaseManager
from remy.memory.embeddings import EmbeddingStore
from remy.memory.goals import (
    GoalExtractor,
    GoalStore,
    _message_has_goal_signal,
    extract_and_store_goals,
)
from remy.models import Goal


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def db(tmp_path):
    manager = DatabaseManager(db_path=str(tmp_path / "goals_test.db"))
    await manager.init()
    await manager.upsert_user(1)
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def goal_store(db):
    embeddings = EmbeddingStore(db)
    return GoalStore(db, embeddings)


def make_mock_claude(return_value: str):
    mock = MagicMock()
    mock.complete = AsyncMock(return_value=return_value)
    return mock


# --------------------------------------------------------------------------- #
# _message_has_goal_signal tests                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("message,expected", [
    ("I want to learn Python", True),
    ("I'm trying to lose weight", True),
    ("My goal is to run a marathon", True),
    ("I need to finish this project", True),
    ("I'm working on a new app", True),
    ("I'd like to travel more", True),
    ("What's the weather today?", False),
    ("Hello, how are you?", False),
    ("Tell me a joke", False),
])
def test_message_has_goal_signal(message, expected):
    assert _message_has_goal_signal(message) == expected


# --------------------------------------------------------------------------- #
# GoalExtractor tests                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_extract_returns_empty_when_no_signal():
    """Should not call Claude if no trigger phrase found."""
    claude = make_mock_claude('[{"title":"should not appear","description":""}]')
    extractor = GoalExtractor(claude)
    goals = await extractor.extract("The weather looks nice today")
    assert goals == []
    claude.complete.assert_not_called()


@pytest.mark.asyncio
async def test_extract_returns_goals_from_valid_json():
    claude = make_mock_claude(
        '[{"title":"Learn Spanish","description":"User wants to learn conversational Spanish"}]'
    )
    extractor = GoalExtractor(claude)
    goals = await extractor.extract("I want to learn Spanish this year")
    assert len(goals) == 1
    assert goals[0].title == "Learn Spanish"


@pytest.mark.asyncio
async def test_extract_returns_multiple_goals():
    claude = make_mock_claude(
        '[{"title":"Run marathon","description":"Running goal"},{"title":"Learn guitar","description":"Music goal"}]'
    )
    extractor = GoalExtractor(claude)
    goals = await extractor.extract("I want to run a marathon and learn guitar")
    assert len(goals) == 2


@pytest.mark.asyncio
async def test_extract_handles_invalid_json_gracefully():
    claude = make_mock_claude("not valid json")
    extractor = GoalExtractor(claude)
    goals = await extractor.extract("I want to start a new project")
    assert goals == []


@pytest.mark.asyncio
async def test_extract_handles_non_list_response():
    claude = make_mock_claude('{"title":"Something"}')
    extractor = GoalExtractor(claude)
    goals = await extractor.extract("I want to do something great")
    assert goals == []


@pytest.mark.asyncio
async def test_extract_truncates_title():
    long_title = "a" * 300
    claude = make_mock_claude(f'[{{"title":"{long_title}","description":"desc"}}]')
    extractor = GoalExtractor(claude)
    goals = await extractor.extract("I want to achieve something extraordinary")
    assert len(goals) == 1
    assert len(goals[0].title) <= 200


# --------------------------------------------------------------------------- #
# GoalStore tests                                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_goal_store_upsert_inserts_new_goal(db, goal_store):
    goals = [Goal(title="Launch remy", description="Personal AI agent")]
    await goal_store.upsert(1, goals)
    active = await goal_store.get_active(1)
    assert len(active) == 1
    assert active[0]["title"] == "Launch remy"


@pytest.mark.asyncio
async def test_goal_store_deduplicates_by_title(db, goal_store):
    goals = [Goal(title="Launch remy")]
    await goal_store.upsert(1, goals)
    await goal_store.upsert(1, goals)
    active = await goal_store.get_active(1)
    assert len(active) == 1


@pytest.mark.asyncio
async def test_goal_store_dedup_handles_substring_titles(db, goal_store):
    """'Launch remy' and 'remy' should deduplicate (substring match)."""
    await goal_store.upsert(1, [Goal(title="Launch remy")])
    await goal_store.upsert(1, [Goal(title="remy")])
    active = await goal_store.get_active(1)
    assert len(active) == 1


@pytest.mark.asyncio
async def test_goal_store_allows_distinct_goals(db, goal_store):
    await goal_store.upsert(1, [Goal(title="Run a marathon")])
    await goal_store.upsert(1, [Goal(title="Learn Spanish")])
    active = await goal_store.get_active(1)
    assert len(active) == 2


@pytest.mark.asyncio
async def test_goal_store_mark_complete(db, goal_store):
    await goal_store.upsert(1, [Goal(title="Run a marathon")])
    active = await goal_store.get_active(1)
    goal_id = active[0]["id"]
    await goal_store.mark_complete(1, goal_id)
    active_after = await goal_store.get_active(1)
    assert len(active_after) == 0


@pytest.mark.asyncio
async def test_goal_store_mark_abandoned(db, goal_store):
    await goal_store.upsert(1, [Goal(title="Write a novel")])
    active = await goal_store.get_active(1)
    goal_id = active[0]["id"]
    await goal_store.mark_abandoned(1, goal_id)
    active_after = await goal_store.get_active(1)
    assert len(active_after) == 0


@pytest.mark.asyncio
async def test_goal_store_user_isolation(db, goal_store):
    """Goals for user 1 should not appear for user 2."""
    await db.upsert_user(2)
    await goal_store.upsert(1, [Goal(title="User 1 goal")])
    active_for_2 = await goal_store.get_active(2)
    assert active_for_2 == []


# --------------------------------------------------------------------------- #
# extract_and_store_goals convenience function                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_extract_and_store_goals_integration(db, goal_store):
    claude = make_mock_claude('[{"title":"Launch SaaS","description":"Build a product"}]')
    extractor = GoalExtractor(claude)
    await extract_and_store_goals(1, "I want to launch a SaaS product", extractor, goal_store)
    active = await goal_store.get_active(1)
    assert any("SaaS" in g["title"] for g in active)


@pytest.mark.asyncio
async def test_extract_and_store_goals_no_signal_skips_claude(db, goal_store):
    claude = make_mock_claude("[]")
    extractor = GoalExtractor(claude)
    # No goal signal in this message — Claude should not be called
    await extract_and_store_goals(1, "The sun is shining today", extractor, goal_store)
    claude.complete.assert_not_called()
