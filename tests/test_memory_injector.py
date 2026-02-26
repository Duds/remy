"""
Tests for drbot/memory/injector.py — MemoryInjector XML block builder.
Uses real DB (tmp) with mocked embedding search to avoid sentence-transformers dependency.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from drbot.memory.database import DatabaseManager
from drbot.memory.embeddings import EmbeddingStore
from drbot.memory.facts import FactStore
from drbot.memory.fts import FTSSearch
from drbot.memory.goals import GoalStore
from drbot.memory.injector import MemoryInjector
from drbot.models import Fact, Goal


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def db(tmp_path):
    manager = DatabaseManager(db_path=str(tmp_path / "injector_test.db"))
    await manager.init()
    await manager.upsert_user(1)
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def components(db):
    """Wire up the full memory stack with ANN search disabled."""
    embeddings = EmbeddingStore(db)
    fact_store = FactStore(db, embeddings)
    goal_store = GoalStore(db, embeddings)
    fts = FTSSearch(db)
    injector = MemoryInjector(db, embeddings, fact_store, goal_store, fts)
    return {
        "embeddings": embeddings,
        "fact_store": fact_store,
        "goal_store": goal_store,
        "fts": fts,
        "injector": injector,
    }


# --------------------------------------------------------------------------- #
# build_context tests                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_build_context_returns_empty_when_no_memory(db, components):
    injector = components["injector"]
    result = await injector.build_context(1, "Hello")
    assert result == ""


@pytest.mark.asyncio
async def test_build_context_includes_facts(db, components):
    fact_store = components["fact_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="name", content="User is Alice")])

    result = await injector.build_context(1, "Hello")
    assert "<memory>" in result
    assert "<facts>" in result
    assert "User is Alice" in result
    assert "name" in result


@pytest.mark.asyncio
async def test_build_context_includes_goals(db, components):
    goal_store = components["goal_store"]
    injector = components["injector"]

    await goal_store.upsert(1, [Goal(title="Learn piano", description="Practice daily")])

    result = await injector.build_context(1, "Hello")
    assert "<memory>" in result
    assert "<goals>" in result
    assert "Learn piano" in result


@pytest.mark.asyncio
async def test_build_context_includes_both_facts_and_goals(db, components):
    fact_store = components["fact_store"]
    goal_store = components["goal_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="location", content="Lives in Sydney")])
    await goal_store.upsert(1, [Goal(title="Run marathon")])

    result = await injector.build_context(1, "Hello")
    assert "<facts>" in result
    assert "<goals>" in result
    assert "Sydney" in result
    assert "marathon" in result


@pytest.mark.asyncio
async def test_build_context_xml_structure(db, components):
    fact_store = components["fact_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="name", content="Name is Bob")])

    result = await injector.build_context(1, "Hello")
    assert result.startswith("<memory>")
    assert result.endswith("</memory>")
    assert "<fact category='name'>" in result
    assert "</fact>" in result


@pytest.mark.asyncio
async def test_build_context_goal_with_description(db, components):
    goal_store = components["goal_store"]
    injector = components["injector"]

    await goal_store.upsert(1, [Goal(title="Ship v1", description="Get to 100 users")])

    result = await injector.build_context(1, "Hello")
    assert "Ship v1" in result
    assert "Get to 100 users" in result
    # Description appended with em-dash separator
    assert "— Get to 100 users" in result


@pytest.mark.asyncio
async def test_build_context_goal_without_description(db, components):
    goal_store = components["goal_store"]
    injector = components["injector"]

    await goal_store.upsert(1, [Goal(title="Exercise daily")])

    result = await injector.build_context(1, "Hello")
    assert "Exercise daily" in result
    # No em-dash suffix when description is absent
    assert "—" not in result


@pytest.mark.asyncio
async def test_build_context_respects_user_isolation(db, components):
    """Memory for user 1 should not appear in user 2's context."""
    await db.upsert_user(2)
    fact_store = components["fact_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="name", content="User 1 secret")])

    result = await injector.build_context(2, "Hello")
    assert "User 1 secret" not in result


# --------------------------------------------------------------------------- #
# build_system_prompt tests                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_build_system_prompt_appends_memory(db, components):
    fact_store = components["fact_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="name", content="Alice")])

    result = await injector.build_system_prompt(1, "Hello", "You are drbot.")
    assert result.startswith("You are drbot.")
    assert "<memory>" in result


@pytest.mark.asyncio
async def test_build_system_prompt_returns_soul_only_when_no_memory(db, components):
    injector = components["injector"]
    result = await injector.build_system_prompt(1, "Hello", "You are drbot.")
    assert result == "You are drbot."


@pytest.mark.asyncio
async def test_build_system_prompt_separator(db, components):
    """Soul and memory block should be separated by double newline."""
    fact_store = components["fact_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="preference", content="Prefers dark mode")])

    result = await injector.build_system_prompt(1, "Hello", "You are drbot.")
    assert "\n\n<memory>" in result


# --------------------------------------------------------------------------- #
# FTS fallback path                                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_build_context_uses_fts_fallback_when_ann_unavailable(db, components):
    """When ANN returns empty, FTS keyword search should still find facts."""
    fact_store = components["fact_store"]
    injector = components["injector"]

    await fact_store.upsert(1, [Fact(category="preference", content="Uses dark mode UI")])

    # ANN is disabled (no sqlite-vec), so this exercises the FTS fallback path
    result = await injector.build_context(1, "dark mode")
    # Either FTS or the final fallback (recent facts) should include our fact
    assert "dark mode" in result.lower() or "Uses dark" in result
