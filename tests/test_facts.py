"""
Tests for drbot/memory/facts.py — FactExtractor (mocked Claude) and FactStore.
No real API calls; ClaudeClient is mocked.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from drbot.memory.database import DatabaseManager
from drbot.memory.embeddings import EmbeddingStore
from drbot.memory.facts import FactExtractor, FactStore, extract_and_store_facts
from drbot.models import Fact


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def db(tmp_path):
    manager = DatabaseManager(db_path=str(tmp_path / "facts_test.db"))
    await manager.init()
    await manager.upsert_user(1)
    yield manager
    await manager.close()


@pytest_asyncio.fixture
async def embedding_store(db):
    """EmbeddingStore with sqlite-vec disabled (just tests SQLite embedding table)."""
    store = EmbeddingStore(db)
    return store


@pytest_asyncio.fixture
async def fact_store(db, embedding_store):
    return FactStore(db, embedding_store)


def make_mock_claude(return_value: str):
    """Return a mock ClaudeClient whose complete() returns the given string."""
    mock = MagicMock()
    mock.complete = AsyncMock(return_value=return_value)
    return mock


# --------------------------------------------------------------------------- #
# FactExtractor tests                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_extract_returns_facts_from_valid_json():
    claude = make_mock_claude(
        '[{"category": "name", "content": "User is called Dale"}]'
    )
    extractor = FactExtractor(claude)
    facts = await extractor.extract("My name is Dale")
    assert len(facts) == 1
    assert facts[0].category == "name"
    assert "Dale" in facts[0].content


@pytest.mark.asyncio
async def test_extract_returns_multiple_facts():
    claude = make_mock_claude(
        '[{"category":"location","content":"Based in Sydney"},{"category":"occupation","content":"Software engineer"}]'
    )
    extractor = FactExtractor(claude)
    facts = await extractor.extract("I live in Sydney and work as a software engineer.")
    assert len(facts) == 2
    categories = {f.category for f in facts}
    assert categories == {"location", "occupation"}


@pytest.mark.asyncio
async def test_extract_returns_empty_for_short_message():
    claude = make_mock_claude("[]")
    extractor = FactExtractor(claude)
    facts = await extractor.extract("hi")
    assert facts == []
    # Should not have called Claude for a <10 char message
    claude.complete.assert_not_called()


@pytest.mark.asyncio
async def test_extract_handles_invalid_json_gracefully():
    claude = make_mock_claude("not valid json at all")
    extractor = FactExtractor(claude)
    facts = await extractor.extract("Some meaningful message about the user")
    assert facts == []


@pytest.mark.asyncio
async def test_extract_handles_non_list_json_gracefully():
    claude = make_mock_claude('{"category":"name","content":"Dale"}')
    extractor = FactExtractor(claude)
    facts = await extractor.extract("Some meaningful message about the user")
    assert facts == []


@pytest.mark.asyncio
async def test_extract_skips_items_missing_required_fields():
    claude = make_mock_claude('[{"category":"name"},{"content":"no category here"}]')
    extractor = FactExtractor(claude)
    facts = await extractor.extract("Some meaningful message about the user")
    # Both items missing required field — first missing "content", second missing "category"
    assert len(facts) == 0


@pytest.mark.asyncio
async def test_extract_truncates_category_and_content():
    long_cat = "x" * 100
    long_content = "y" * 600
    claude = make_mock_claude(
        f'[{{"category":"{long_cat}","content":"{long_content}"}}]'
    )
    extractor = FactExtractor(claude)
    facts = await extractor.extract("Some meaningful message")
    assert len(facts) == 1
    assert len(facts[0].category) <= 50
    assert len(facts[0].content) <= 500


# --------------------------------------------------------------------------- #
# FactStore tests                                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_fact_store_upsert_inserts_new_fact(db, fact_store):
    facts = [Fact(category="name", content="User is Alice")]
    await fact_store.upsert(1, facts)
    stored = await fact_store.get_for_user(1)
    assert len(stored) == 1
    assert stored[0]["content"] == "User is Alice"


@pytest.mark.asyncio
async def test_fact_store_deduplicates_identical_content(db, fact_store):
    facts = [Fact(category="name", content="User is Alice")]
    await fact_store.upsert(1, facts)
    await fact_store.upsert(1, facts)  # same again
    stored = await fact_store.get_for_user(1)
    assert len(stored) == 1  # not duplicated


@pytest.mark.asyncio
async def test_fact_store_dedup_is_case_insensitive(db, fact_store):
    await fact_store.upsert(1, [Fact(category="name", content="user is alice")])
    await fact_store.upsert(1, [Fact(category="name", content="User is Alice")])
    stored = await fact_store.get_for_user(1)
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_fact_store_allows_different_content(db, fact_store):
    await fact_store.upsert(1, [Fact(category="location", content="Lives in Sydney")])
    await fact_store.upsert(1, [Fact(category="location", content="Office in Melbourne")])
    stored = await fact_store.get_for_user(1)
    assert len(stored) == 2


@pytest.mark.asyncio
async def test_fact_store_get_by_category(db, fact_store):
    await fact_store.upsert(1, [
        Fact(category="name", content="User is Alice"),
        Fact(category="location", content="Lives in Sydney"),
    ])
    name_facts = await fact_store.get_by_category(1, "name")
    assert len(name_facts) == 1
    assert name_facts[0]["category"] == "name"


@pytest.mark.asyncio
async def test_fact_store_respects_user_isolation(db, fact_store):
    """Facts for user 1 should not appear for user 2."""
    await db.upsert_user(2)
    await fact_store.upsert(1, [Fact(category="name", content="Alice")])
    stored_for_2 = await fact_store.get_for_user(2)
    assert stored_for_2 == []


# --------------------------------------------------------------------------- #
# extract_and_store_facts convenience function                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_extract_and_store_facts_integration(db, fact_store):
    """extract_and_store_facts should call extractor then store results."""
    claude = make_mock_claude('[{"category":"preference","content":"Prefers dark mode"}]')
    extractor = FactExtractor(claude)
    await extract_and_store_facts(1, "I always use dark mode.", extractor, fact_store)
    stored = await fact_store.get_for_user(1)
    assert any("dark mode" in s["content"].lower() for s in stored)


@pytest.mark.asyncio
async def test_extract_and_store_facts_handles_extraction_error(db, fact_store):
    """Should not raise even if extractor throws."""
    claude = MagicMock()
    claude.complete = AsyncMock(side_effect=RuntimeError("API down"))
    extractor = FactExtractor(claude)
    # Should not raise
    await extract_and_store_facts(1, "I live in Sydney", extractor, fact_store)
