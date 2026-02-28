"""
Tests for proactive memory storage behaviour (US-proactive-memory-storage).

These tests verify that:
1. The manage_memory tool schema supports proactive use cases
2. The KnowledgeStore correctly handles add/update/delete flows
3. Semantic deduplication prevents duplicate facts

The actual Claude behaviour (whether it calls manage_memory proactively)
is governed by SOUL.md and the tool description — these tests verify
the infrastructure supports the intended behaviour.
"""

import pytest
import pytest_asyncio
import json
from unittest.mock import MagicMock, AsyncMock

from remy.memory.database import DatabaseManager
from remy.memory.knowledge import KnowledgeStore
from remy.memory.embeddings import EmbeddingStore
from remy.models import KnowledgeItem
from remy.ai.tool_registry import ToolRegistry, TOOL_SCHEMAS


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh DB per test with mocked embeddings."""
    manager = DatabaseManager(db_path=str(tmp_path / "test_proactive.db"))
    await manager.init()
    await manager.upsert_user(42)
    
    embeddings = MagicMock(spec=EmbeddingStore)
    embeddings.upsert_embedding = AsyncMock(return_value=1)
    embeddings.search_similar_for_type = AsyncMock(return_value=[])
    
    yield manager, embeddings
    await manager.close()


def make_registry(**kwargs) -> ToolRegistry:
    """Construct a ToolRegistry with sensible mock defaults."""
    defaults = dict(
        logs_dir="/tmp/test_logs",
        goal_store=None,
        fact_store=None,
        board_orchestrator=None,
        claude_client=None,
        ollama_base_url="http://localhost:11434",
        model_complex="claude-sonnet-4-6",
    )
    defaults.update(kwargs)
    return ToolRegistry(**defaults)


USER_ID = 42


# --------------------------------------------------------------------------- #
# Tool schema tests                                                             #
# --------------------------------------------------------------------------- #

def test_manage_memory_tool_exists():
    """manage_memory tool is present in TOOL_SCHEMAS."""
    names = {s["name"] for s in TOOL_SCHEMAS}
    assert "manage_memory" in names


def test_manage_memory_description_mentions_proactive():
    """Tool description instructs proactive use."""
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "manage_memory")
    desc = schema["description"].lower()
    assert "proactive" in desc


def test_manage_memory_description_mentions_silent():
    """Tool description instructs silent storage (no announcement)."""
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "manage_memory")
    desc = schema["description"].lower()
    assert "silent" in desc


def test_manage_memory_supports_all_actions():
    """Tool schema supports add, update, delete actions."""
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "manage_memory")
    action_enum = schema["input_schema"]["properties"]["action"]["enum"]
    assert set(action_enum) == {"add", "update", "delete"}


def test_manage_memory_has_category_field():
    """Tool schema includes category field for fact classification."""
    schema = next(s for s in TOOL_SCHEMAS if s["name"] == "manage_memory")
    props = schema["input_schema"]["properties"]
    assert "category" in props
    # Check it mentions the key categories from SOUL.md
    cat_desc = props["category"]["description"].lower()
    assert "relationship" in cat_desc
    assert "preference" in cat_desc
    assert "health" in cat_desc


# --------------------------------------------------------------------------- #
# Proactive storage scenarios                                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_store_completed_task(db):
    """Scenario: 'The tyre's done' → fact stored with date context."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    # Simulate what Claude would call via manage_memory
    item_id = await store.add_item(
        USER_ID, 
        "fact", 
        "Tyre collected from Tyrepower (2026-03-01)",
        {"category": "other"}
    )
    
    assert item_id > 0
    
    # Verify stored correctly
    async with manager.get_connection() as conn:
        row = (await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE id=?", (item_id,)
        ))[0]
    
    assert "Tyre collected" in row["content"]
    assert json.loads(row["metadata"])["category"] == "other"


@pytest.mark.asyncio
async def test_store_persons_plans(db):
    """Scenario: 'Alex is away for the weekend' → fact stored under relationship."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    item_id = await store.add_item(
        USER_ID,
        "fact",
        "Alex away for the weekend (2026-03-01)",
        {"category": "relationship"}
    )
    
    async with manager.get_connection() as conn:
        row = (await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE id=?", (item_id,)
        ))[0]
    
    assert "Alex away" in row["content"]
    assert json.loads(row["metadata"])["category"] == "relationship"


@pytest.mark.asyncio
async def test_store_decision(db):
    """Scenario: 'I've decided to go with CommBank' → fact stored under preference."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    item_id = await store.add_item(
        USER_ID,
        "fact",
        "Decided to go with CommBank mortgage",
        {"category": "preference"}
    )
    
    async with manager.get_connection() as conn:
        row = (await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE id=?", (item_id,)
        ))[0]
    
    assert "CommBank" in row["content"]
    assert json.loads(row["metadata"])["category"] == "preference"


@pytest.mark.asyncio
async def test_store_health_update(db):
    """Scenario: 'I started seeing a physio' → fact stored under health."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    item_id = await store.add_item(
        USER_ID,
        "fact",
        "Started seeing a physiotherapist",
        {"category": "health"}
    )
    
    async with manager.get_connection() as conn:
        row = (await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE id=?", (item_id,)
        ))[0]
    
    assert "physiotherapist" in row["content"]
    assert json.loads(row["metadata"])["category"] == "health"


@pytest.mark.asyncio
async def test_update_outdated_fact(db):
    """Scenario: 'Alex is back' updates/removes the 'Alex is away' fact."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    # First, store the original fact
    item_id = await store.add_item(
        USER_ID,
        "fact",
        "Alex away for the weekend",
        {"category": "relationship"}
    )
    
    # Now update it (simulating what Claude would do)
    success = await store.update(
        USER_ID,
        item_id,
        content="Alex is back (2026-03-03)",
        metadata={"category": "relationship"}
    )
    
    assert success is True
    
    async with manager.get_connection() as conn:
        row = (await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE id=?", (item_id,)
        ))[0]
    
    assert "Alex is back" in row["content"]


@pytest.mark.asyncio
async def test_delete_outdated_fact(db):
    """Scenario: Delete a fact that's no longer relevant."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    item_id = await store.add_item(
        USER_ID,
        "fact",
        "Alex away for the weekend",
        {"category": "relationship"}
    )
    
    success = await store.delete(USER_ID, item_id)
    assert success is True
    
    async with manager.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE id=?", (item_id,)
        )
    
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_exact_deduplication(db):
    """Exact duplicate facts are not stored twice."""
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    
    item = KnowledgeItem(
        entity_type="fact",
        content="Dale lives in Canberra",
        metadata={"category": "location"},
        confidence=1.0
    )
    
    await store.upsert(USER_ID, [item])
    await store.upsert(USER_ID, [item])  # Should dedup
    
    async with manager.get_connection() as conn:
        rows = await conn.execute_fetchall(
            "SELECT * FROM knowledge WHERE user_id=? AND entity_type='fact'",
            (USER_ID,)
        )
    
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Tool dispatch tests                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_dispatch_manage_memory_add_with_category():
    """manage_memory add action stores fact with correct category."""
    ks = MagicMock()
    ks.add_item = AsyncMock(return_value=123)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "add",
        "content": "Tyre collected from Tyrepower (2026-03-01)",
        "category": "other"
    }, USER_ID)
    
    assert "Fact stored" in result
    ks.add_item.assert_called_once_with(
        USER_ID, "fact", 
        "Tyre collected from Tyrepower (2026-03-01)", 
        {"category": "other"}
    )


@pytest.mark.asyncio
async def test_dispatch_manage_memory_add_relationship():
    """manage_memory stores relationship facts correctly."""
    ks = MagicMock()
    ks.add_item = AsyncMock(return_value=456)
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "add",
        "content": "Alex away for the weekend",
        "category": "relationship"
    }, USER_ID)
    
    assert "Fact stored" in result
    ks.add_item.assert_called_once_with(
        USER_ID, "fact",
        "Alex away for the weekend",
        {"category": "relationship"}
    )


@pytest.mark.asyncio
async def test_dispatch_manage_memory_update_requires_fact_id():
    """Update action without fact_id returns helpful error."""
    ks = MagicMock()
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "update",
        "content": "New content"
    }, USER_ID)
    
    assert "fact_id" in result.lower()


@pytest.mark.asyncio
async def test_dispatch_manage_memory_delete_requires_fact_id():
    """Delete action without fact_id returns helpful error."""
    ks = MagicMock()
    reg = make_registry(knowledge_store=ks)
    
    result = await reg.dispatch("manage_memory", {
        "action": "delete"
    }, USER_ID)
    
    assert "fact_id" in result.lower()
