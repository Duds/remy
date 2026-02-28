"""Tests for remy/memory/knowledge.py — unified knowledge store."""

import pytest
import pytest_asyncio
import json
from unittest.mock import MagicMock

from remy.memory.database import DatabaseManager
from remy.memory.knowledge import KnowledgeStore
from remy.memory.embeddings import EmbeddingStore
from remy.models import KnowledgeItem


@pytest_asyncio.fixture
async def db(tmp_path):
    """Fresh in-memory-style DB per test."""
    manager = DatabaseManager(db_path=str(tmp_path / "test_knowledge.db"))
    await manager.init()
    # Ensure user exists for foreign key constraints
    await manager.upsert_user(42)
    # Mock embeddings to avoid SentenceTransformer loading
    embeddings = MagicMock(spec=EmbeddingStore)
    embeddings.upsert_embedding.return_value = 1
    yield manager, embeddings
    await manager.close()


@pytest.mark.asyncio
async def test_upsert_deduplication(db):
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    user_id = 42
    
    item = KnowledgeItem(entity_type="fact", content="Likes blue", metadata={"category": "preference"})
    await store.upsert(user_id, [item])
    await store.upsert(user_id, [item]) # Should dedup
    
    async with manager.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT * FROM knowledge WHERE user_id=?", (user_id,))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_add_item(db):
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    user_id = 42
    
    item_id = await store.add_item(user_id, "goal", "Launch product", {"status": "active"})
    assert item_id > 0
    
    async with manager.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT * FROM knowledge WHERE id=?", (item_id,))
    assert len(rows) == 1
    assert rows[0]["entity_type"] == "goal"
    assert rows[0]["content"] == "Launch product"
    assert json.loads(rows[0]["metadata"])["status"] == "active"


@pytest.mark.asyncio
async def test_update(db):
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    user_id = 42
    item_id = await store.add_item(user_id, "fact", "Old content")
    
    success = await store.update(user_id, item_id, content="New content", metadata={"cat": "updated"})
    assert success is True
    
    async with manager.get_connection() as conn:
        row = (await conn.execute_fetchall("SELECT * FROM knowledge WHERE id=?", (item_id,)))[0]
    assert row["content"] == "New content"
    assert json.loads(row["metadata"])["cat"] == "updated"


@pytest.mark.asyncio
async def test_delete(db):
    manager, embeddings = db
    store = KnowledgeStore(manager, embeddings)
    user_id = 42
    item_id = await store.add_item(user_id, "fact", "To delete")
    
    success = await store.delete(user_id, item_id)
    assert success is True
    
    async with manager.get_connection() as conn:
        rows = await conn.execute_fetchall("SELECT * FROM knowledge WHERE id=?", (item_id,))
    assert len(rows) == 0
