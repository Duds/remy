"""
Tests for remy/memory/injector.py — MemoryInjector XML block builder.
Uses real DB (tmp) with mocked embedding search to avoid sentence-transformers dependency.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from remy.memory.database import DatabaseManager
from remy.memory.embeddings import EmbeddingStore
from remy.memory.knowledge import KnowledgeStore
from remy.memory.fts import FTSSearch
from remy.memory.injector import MemoryInjector
from remy.models import KnowledgeItem


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
    knowledge_store = KnowledgeStore(db, embeddings)
    fts = FTSSearch(db)
    injector = MemoryInjector(db, embeddings, knowledge_store, fts)
    return {
        "embeddings": embeddings,
        "knowledge_store": knowledge_store,
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
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="User is Alice", metadata={"category": "name"})])

    result = await injector.build_context(1, "Hello")
    assert "<memory>" in result
    assert "<facts>" in result
    assert "User is Alice" in result
    assert "name" in result


@pytest.mark.asyncio
async def test_build_context_includes_goals(db, components):
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="goal", content="Learn piano", metadata={"description": "Practice daily"})])

    result = await injector.build_context(1, "Hello")
    assert "<memory>" in result
    assert "<goals>" in result
    assert "Learn piano" in result


@pytest.mark.asyncio
async def test_build_context_includes_both_facts_and_goals(db, components):
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="Lives in Sydney", metadata={"category": "location"})])
    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="goal", content="Run marathon", metadata={})])

    result = await injector.build_context(1, "Hello")
    assert "<facts>" in result
    assert "<goals>" in result
    assert "Sydney" in result
    assert "marathon" in result


@pytest.mark.asyncio
async def test_build_context_xml_structure(db, components):
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="Name is Bob", metadata={"category": "name"})])

    result = await injector.build_context(1, "Hello")
    assert result.startswith("<memory>")
    assert result.endswith("</memory>")
    assert "<fact" in result
    assert "category='name'" in result
    assert "</fact>" in result


@pytest.mark.asyncio
async def test_build_context_goal_with_description(db, components):
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="goal", content="Ship v1", metadata={"description": "Get to 100 users"})])

    result = await injector.build_context(1, "Hello")
    assert "Ship v1" in result
    assert "Get to 100 users" in result
    # Description appended with em-dash separator
    assert "— Get to 100 users" in result


@pytest.mark.asyncio
async def test_build_context_goal_without_description(db, components):
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="goal", content="Exercise daily", metadata={})])

    result = await injector.build_context(1, "Hello")
    assert "Exercise daily" in result
    # No em-dash suffix when description is absent
    assert "—" not in result


@pytest.mark.asyncio
async def test_build_context_respects_user_isolation(db, components):
    """Memory for user 1 should not appear in user 2's context."""
    await db.upsert_user(2)
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="User 1 secret", metadata={"category": "name"})])

    result = await injector.build_context(2, "Hello")
    assert "User 1 secret" not in result


# --------------------------------------------------------------------------- #
# build_system_prompt tests                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_build_system_prompt_appends_memory(db, components):
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="Alice", metadata={"category": "name"})])

    result = await injector.build_system_prompt(1, "Hello", "You are remy.")
    assert result.startswith("You are remy.")
    assert "<memory>" in result


@pytest.mark.asyncio
async def test_build_system_prompt_returns_soul_only_when_no_memory(db, components):
    injector = components["injector"]
    result = await injector.build_system_prompt(1, "Hello", "You are remy.")
    assert result == "You are remy."


@pytest.mark.asyncio
async def test_build_system_prompt_separator(db, components):
    """Soul and memory block should be separated by double newline."""
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="Prefers dark mode", metadata={"category": "preference"})])

    result = await injector.build_system_prompt(1, "Hello", "You are remy.")
    assert "\n\n<memory>" in result


# --------------------------------------------------------------------------- #
# FTS fallback path                                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_build_context_uses_fts_fallback_when_ann_unavailable(db, components):
    """When ANN returns empty, FTS keyword search should still find facts."""
    knowledge_store = components["knowledge_store"]
    injector = components["injector"]

    await knowledge_store.upsert(1, [KnowledgeItem(entity_type="fact", content="Uses dark mode UI", metadata={"category": "preference"})])

    # ANN is disabled (no sqlite-vec), so this exercises the fallback path
    result = await injector.build_context(1, "dark mode")
    assert "dark mode" in result.lower() or "Uses dark" in result
