"""
Unified Knowledge extraction and storage.

KnowledgeExtractor uses Claude Haiku to identify facts, goals, and shopping items
from user messages, mapping fuzzy language (e.g., "buy" vs "get groceries")
to consistent entity types.

KnowledgeStore persists them to a unified SQLite table with ID visibility.
"""

import json
import logging
import os
from typing import Any, Optional

from ..ai.claude_client import ClaudeClient
from ..config import settings
from ..models import KnowledgeItem
from .database import DatabaseManager
from .embeddings import EmbeddingStore

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM = """You extract structured knowledge items from user messages.
Return ONLY a JSON array of objects, each with "entity_type", "content", and "metadata".

Entity Types:
- shopping_item: Items to buy, groceries, supermarket lists. (Phrases: "buy", "need some", "get from shops")
- goal: Intentions, objectives, tasks user is working on. (Phrases: "I want to", "I'm trying to", "working on", "objective")
- fact: Personal details about the user. (Categories: name, age, location, preference, relationship, health, project).

Extraction Rules:
1. "shopping_item": Metadata should be empty {}. Content is just the item name.
2. "goal": Metadata can include {"status": "active"}. Content is the goal title.
3. "fact": Metadata must include {"category": "..."} using one of the legal categories.

Return [] if no knowledge items are found.
Example: [{"entity_type": "shopping_item", "content": "milk", "metadata": {}}, {"entity_type": "goal", "content": "Build a robot", "metadata": {"status": "active"}}]"""

_EXTRACTION_PROMPT = 'Extract knowledge items from this message:\n\n"""{message}"""'

class KnowledgeExtractor:
    """Uses Claude Haiku to extract unified knowledge items from user messages."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def extract(self, message: str) -> list[KnowledgeItem]:
        """Extract facts, goals, or shopping items. Returns empty list on failure."""
        if len(message.strip()) < 5:
            return []
        
        try:
            raw = await self._claude.complete(
                messages=[
                    {
                        "role": "user",
                        "content": _EXTRACTION_PROMPT.format(message=message[:1000]),
                    }
                ],
                system=_EXTRACTION_SYSTEM,
                model=settings.model_simple,
                max_tokens=1000,
            )
            
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
            
            data = json.loads(cleaned.strip())
            if not isinstance(data, list):
                return []
            
            items = []
            for d in data:
                if isinstance(d, dict) and "entity_type" in d and "content" in d:
                    items.append(
                        KnowledgeItem(
                            entity_type=d["entity_type"],
                            content=str(d["content"])[:500],
                            metadata=d.get("metadata", {}),
                            confidence=d.get("confidence", 1.0)
                        )
                    )
            return items
        except Exception as e:
            logger.debug("Knowledge extraction failed: %s", e)
            return []

class KnowledgeStore:
    """Persists and retrieves knowledge items in a unified SQLite table."""

    def __init__(self, db: DatabaseManager, embeddings: EmbeddingStore) -> None:
        self._db = db
        self._embeddings = embeddings

    async def upsert(self, user_id: int, items: list[KnowledgeItem]) -> None:
        """Insert new knowledge items, skipping exact content duplicates."""
        if not items:
            return
        
        # Simple deduplication per user/type
        for item in items:
            async with self._db.get_connection() as conn:
                existing = await conn.execute_fetchall(
                    "SELECT id FROM knowledge WHERE user_id=? AND entity_type=? AND LOWER(content)=LOWER(?)",
                    (user_id, item.entity_type, item.content)
                )
                if existing:
                    continue
            
            await self._insert(user_id, item)

    async def _insert(self, user_id: int, item: KnowledgeItem) -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO knowledge (user_id, entity_type, content, metadata, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, item.entity_type, item.content, json.dumps(item.metadata), item.confidence),
            )
            item_id = cursor.lastrowid
            await conn.commit()

        # Update embedding
        try:
            emb_id = await self._embeddings.upsert_embedding(
                user_id, f"knowledge_{item.entity_type}", item_id, item.content
            )
            async with self._db.get_connection() as conn:
                await conn.execute(
                    "UPDATE knowledge SET embedding_id=? WHERE id=?",
                    (emb_id, item_id),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("Could not embed knowledge item %d: %s", item_id, e)
        
        return item_id

    async def get_by_type(self, user_id: int, entity_type: str, limit: int = 50) -> list[KnowledgeItem]:
        """Fetch items of a specific type for the user."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, entity_type, content, metadata, confidence, created_at
                FROM knowledge WHERE user_id=? AND entity_type=?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, entity_type, limit),
            )
            return [
                KnowledgeItem(
                    id=row["id"],
                    entity_type=row["entity_type"],
                    content=row["content"],
                    metadata=json.loads(row["metadata"]),
                    confidence=row["confidence"]
                ) for row in rows
            ]

    async def update(self, user_id: int, item_id: int, content: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
        """Update an existing knowledge item."""
        updates = []
        params = []
        if content:
            updates.append("content=?")
            params.append(content)
        if metadata:
            updates.append("metadata=?")
            params.append(json.dumps(metadata))
        
        if not updates:
            return False
        
        params.extend([item_id, user_id])
        sql = f"UPDATE knowledge SET {', '.join(updates)}, updated_at=datetime('now') WHERE id=? AND user_id=?"
        
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(sql, tuple(params))
            await conn.commit()
            return cursor.rowcount > 0

    async def delete(self, user_id: int, item_id: int) -> bool:
        """Delete a knowledge item."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM knowledge WHERE id=? AND user_id=?",
                (item_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def migrate_legacy_data(self, user_id: int, grocery_file: Optional[str] = None) -> dict[str, int]:
        """One-time migration from facts, goals, and grocery text file."""
        stats = {"facts": 0, "goals": 0, "groceries": 0}
        
        async with self._db.get_connection() as conn:
            # 1. Migrate Facts
            fact_rows = await conn.execute_fetchall("SELECT category, content, confidence FROM facts WHERE user_id=?", (user_id,))
            for row in fact_rows:
                await self.upsert(user_id, [KnowledgeItem(
                    entity_type="fact",
                    content=row["content"],
                    metadata={"category": row["category"]},
                    confidence=row["confidence"]
                )])
                stats["facts"] += 1
            
            # 2. Migrate Goals
            goal_rows = await conn.execute_fetchall("SELECT title, description, status FROM goals WHERE user_id=?", (user_id,))
            for row in goal_rows:
                await self.upsert(user_id, [KnowledgeItem(
                    entity_type="goal",
                    content=row["title"],
                    metadata={"description": row["description"], "status": row["status"]}
                )])
                stats["goals"] += 1
                
        # 3. Migrate Groceries
        if grocery_file and os.path.exists(grocery_file):
            try:
                with open(grocery_file, encoding="utf-8") as f:
                    for line in f:
                        item = line.strip().strip("- ").strip()
                        if item:
                            await self.upsert(user_id, [KnowledgeItem(
                                entity_type="shopping_item",
                                content=item
                            )])
                            stats["groceries"] += 1
            except Exception as e:
                logger.warning("Could not migrate grocery file: %s", e)
                
        return stats

async def extract_and_store_knowledge(
    user_id: int,
    message: str,
    extractor: KnowledgeExtractor,
    store: KnowledgeStore,
) -> None:
    """Convenience background task."""
    try:
        items = await extractor.extract(message)
        if items:
            await store.upsert(user_id, items)
            logger.debug("Stored %d knowledge items for user %d", len(items), user_id)
    except Exception as e:
        logger.warning("extract_and_store_knowledge failed: %s", e)
