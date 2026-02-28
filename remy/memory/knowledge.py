"""
Unified Knowledge extraction and storage.

KnowledgeExtractor uses Claude Haiku to identify facts, goals, and shopping items
from user messages, mapping fuzzy language (e.g., "buy" vs "get groceries")
to consistent entity types.

KnowledgeStore persists them to a unified SQLite table with ID visibility.
Includes semantic deduplication: near-duplicate facts are merged rather than
creating new rows (US-improved-persistent-memory).
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

# Valid fact categories for the expanded taxonomy
FACT_CATEGORIES = frozenset([
    "name", "location", "occupation", "health", "medical", "finance",
    "hobby", "relationship", "preference", "deadline", "project", "other"
])

_EXTRACTION_SYSTEM = """You extract structured knowledge items from user messages.
Return ONLY a JSON array of objects, each with "entity_type", "content", "metadata", and "confidence".

Entity Types:
- shopping_item: Items to buy, groceries, supermarket lists. (Phrases: "buy", "need some", "get from shops")
- goal: Intentions, objectives, tasks user is working on. (Phrases: "I want to", "I'm trying to", "working on", "objective")
- fact: Personal details about the user.

Fact Categories (use in metadata.category):
- name: User's name or preferred name
- location: Where they live, work location, places they frequent
- occupation: Job, profession, workplace, role
- health: General health conditions, injuries, recovery status
- medical: Diagnoses, medications, treatments, allergies (more specific than health)
- finance: Banking, mortgage, investments, financial decisions
- hobby: Hobbies, sports, interests, leisure activities
- relationship: Family members, friends, colleagues, pets
- preference: Likes, dislikes, favourites, personal preferences
- deadline: Upcoming dates, appointments, due dates, events
- project: Software projects, home projects, work projects
- other: Anything that doesn't fit the above

Extraction Rules:
1. "shopping_item": Metadata should be empty {}. Content is just the item name.
2. "goal": Metadata can include {"status": "active"}. Content is the goal title.
3. "fact": Metadata must include {"category": "..."} using one of the legal categories above.

Confidence Scoring (you MUST include "confidence" on every item):
- 0.9–1.0: Explicit, unambiguous statement. e.g. "My name is Alice", "I live in Sydney".
- 0.7–0.8: Reasonably clear but slightly indirect. e.g. "I'm based in Sydney these days".
- 0.5–0.6: Inferred or contextual — stated implicitly or hedged. e.g. "I think I prefer Python".
- below 0.5: Speculation or very uncertain — do not extract unless clearly relevant.

Return [] if no knowledge items are found.
Example: [{"entity_type": "fact", "content": "Lives in Sydney", "metadata": {"category": "location"}, "confidence": 0.95}, {"entity_type": "goal", "content": "Build a robot", "metadata": {"status": "active"}, "confidence": 0.8}]"""

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
    """Persists and retrieves knowledge items in a unified SQLite table.
    
    Includes semantic deduplication: when a new fact is extracted, it's compared
    to existing facts using ANN cosine distance. If a near-duplicate exists
    (distance < fact_merge_threshold), the existing fact is superseded rather
    than creating a new row.
    """

    def __init__(self, db: DatabaseManager, embeddings: EmbeddingStore) -> None:
        self._db = db
        self._embeddings = embeddings

    async def upsert(
        self, user_id: int, items: list[KnowledgeItem], session_key: str = ""
    ) -> None:
        """Insert new knowledge items with semantic deduplication.
        
        For facts, performs ANN similarity check within the same category.
        If a semantically similar fact exists (distance < threshold), the
        existing fact is updated (superseded) rather than inserting a new row.
        """
        if not items:
            return
        
        for item in items:
            # Fast path: exact string match
            async with self._db.get_connection() as conn:
                existing = await conn.execute_fetchall(
                    "SELECT id FROM knowledge WHERE user_id=? AND entity_type=? AND LOWER(content)=LOWER(?)",
                    (user_id, item.entity_type, item.content)
                )
                if existing:
                    continue
            
            # Semantic deduplication for facts only
            if item.entity_type == "fact":
                category = item.metadata.get("category", "other")
                source_type = f"knowledge_fact"
                
                similar = await self._embeddings.search_similar_for_type(
                    user_id, item.content, source_type=source_type, limit=5
                )
                
                # Filter to same category and check threshold
                merged = False
                for match in similar:
                    if match.get("distance", 1.0) >= settings.fact_merge_threshold:
                        continue
                    
                    # Fetch the matched item to check category
                    match_id = match.get("source_id")
                    if not match_id:
                        continue
                    
                    async with self._db.get_connection() as conn:
                        row = await conn.execute_fetchall(
                            "SELECT id, metadata FROM knowledge WHERE id=? AND user_id=?",
                            (match_id, user_id)
                        )
                        if not row:
                            continue
                        
                        match_meta = json.loads(row[0]["metadata"])
                        match_category = match_meta.get("category", "other")
                        
                        # Only merge within same category
                        if match_category != category:
                            continue
                        
                        # Supersede: update the existing fact
                        old_content = match.get("content_text", "")
                        await self._supersede(
                            user_id, match_id, item.content, item.metadata, session_key
                        )
                        logger.debug(
                            "Merged fact (d=%.3f): %r → %r",
                            match["distance"], old_content, item.content
                        )
                        merged = True
                        break
                
                if merged:
                    continue
            
            await self._insert(user_id, item, session_key=session_key)

    async def _supersede(
        self,
        user_id: int,
        item_id: int,
        new_content: str,
        new_metadata: dict,
        session_key: str = "",
    ) -> None:
        """Update an existing item with new content (supersession)."""
        async with self._db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE knowledge 
                SET content=?, metadata=?, updated_at=datetime('now'),
                    source_session=COALESCE(?, source_session)
                WHERE id=? AND user_id=?
                """,
                (new_content, json.dumps(new_metadata), session_key or None, item_id, user_id),
            )
            await conn.commit()
        
        # Re-embed with new content
        try:
            emb_id = await self._embeddings.upsert_embedding(
                user_id, "knowledge_fact", item_id, new_content
            )
            async with self._db.get_connection() as conn:
                await conn.execute(
                    "UPDATE knowledge SET embedding_id=? WHERE id=?",
                    (emb_id, item_id),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("Could not re-embed superseded item %d: %s", item_id, e)

    async def _insert(self, user_id: int, item: KnowledgeItem, session_key: str = "") -> int:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO knowledge (user_id, entity_type, content, metadata, confidence,
                                       last_referenced_at, source_session)
                VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
                """,
                (user_id, item.entity_type, item.content, json.dumps(item.metadata),
                 item.confidence, session_key or None),
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

    async def add_item(self, user_id: int, entity_type: str, content: str, metadata: dict | None = None) -> int:
        """Manually insert an item bypassing extraction. Returns the new item ID."""
        item = KnowledgeItem(
            entity_type=entity_type,
            content=content,
            metadata=metadata or {},
            confidence=1.0  # Assumed explicitly true since user asked to store it.
        )
        await self.upsert(user_id, [item])

        # Retrieve the ID of what was just inserted
        async with self._db.get_connection() as conn:
            row = await conn.execute_fetchall(
                "SELECT id FROM knowledge WHERE user_id=? AND entity_type=? AND content=? ORDER BY id DESC LIMIT 1",
                (user_id, entity_type, content),
            )
            return row[0]["id"] if row else 0

    async def get_by_type(
        self, user_id: int, entity_type: str, limit: int = 50, min_confidence: float = 0.5
    ) -> list[KnowledgeItem]:
        """Fetch items of a specific type for the user, filtered by minimum confidence."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, entity_type, content, metadata, confidence, created_at,
                       last_referenced_at, source_session
                FROM knowledge WHERE user_id=? AND entity_type=? AND confidence >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, entity_type, min_confidence, limit),
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

    async def get_memory_summary(self, user_id: int) -> dict[str, Any]:
        """Return a structured overview of stored memory for a user.
        
        Returns:
            dict with keys: total_facts, total_goals, recent_facts_7d,
            categories (dict of category -> count), oldest_fact,
            potentially_stale (facts not referenced in 90+ days)
        """
        async with self._db.get_connection() as conn:
            # Total counts
            fact_count = await conn.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM knowledge WHERE user_id=? AND entity_type='fact'",
                (user_id,)
            )
            goal_count = await conn.execute_fetchall(
                "SELECT COUNT(*) as cnt FROM knowledge WHERE user_id=? AND entity_type='goal'",
                (user_id,)
            )
            
            # Recent facts (last 7 days)
            recent = await conn.execute_fetchall(
                """SELECT COUNT(*) as cnt FROM knowledge 
                   WHERE user_id=? AND entity_type='fact' 
                   AND created_at >= datetime('now', '-7 days')""",
                (user_id,)
            )
            
            # Category breakdown
            cat_rows = await conn.execute_fetchall(
                """SELECT json_extract(metadata, '$.category') as cat, COUNT(*) as cnt
                   FROM knowledge WHERE user_id=? AND entity_type='fact'
                   GROUP BY cat ORDER BY cnt DESC""",
                (user_id,)
            )
            categories = {row["cat"] or "other": row["cnt"] for row in cat_rows}
            
            # Oldest fact
            oldest = await conn.execute_fetchall(
                """SELECT content, created_at FROM knowledge 
                   WHERE user_id=? AND entity_type='fact'
                   ORDER BY created_at ASC LIMIT 1""",
                (user_id,)
            )
            
            # Potentially stale (not referenced in 90+ days)
            stale = await conn.execute_fetchall(
                """SELECT COUNT(*) as cnt FROM knowledge 
                   WHERE user_id=? AND entity_type='fact'
                   AND (last_referenced_at IS NULL 
                        OR last_referenced_at < datetime('now', '-90 days'))""",
                (user_id,)
            )
            
        return {
            "total_facts": fact_count[0]["cnt"] if fact_count else 0,
            "total_goals": goal_count[0]["cnt"] if goal_count else 0,
            "recent_facts_7d": recent[0]["cnt"] if recent else 0,
            "categories": categories,
            "oldest_fact": {
                "content": oldest[0]["content"],
                "created_at": oldest[0]["created_at"]
            } if oldest else None,
            "potentially_stale": stale[0]["cnt"] if stale else 0,
        }

    async def update_last_referenced(self, user_id: int, item_ids: list[int]) -> None:
        """Update last_referenced_at for items that appeared in a query result."""
        if not item_ids:
            return
        placeholders = ",".join("?" * len(item_ids))
        async with self._db.get_connection() as conn:
            await conn.execute(
                f"""UPDATE knowledge SET last_referenced_at = datetime('now')
                    WHERE user_id=? AND id IN ({placeholders})""",
                (user_id, *item_ids),
            )
            await conn.commit()

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
