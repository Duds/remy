"""
Fact extraction and storage.

FactExtractor calls Claude Haiku with a structured prompt to identify facts
about the user from their messages. FactStore persists them to SQLite with
basic deduplication.
"""

import json
import logging
from typing import Any

from ..ai.claude_client import ClaudeClient
from ..config import settings
from ..models import Fact
from .database import DatabaseManager
from .embeddings import EmbeddingStore

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM = """You extract facts about the user from their messages.
Return ONLY a JSON array of objects, each with "category" and "content" fields.
Categories: name, age, location, occupation, preference, relationship, health, project, other.
Extract only clear, specific facts. If there are no facts, return [].
Example: [{"category": "name", "content": "User's name is Dale"}, {"category": "location", "content": "User is based in Sydney"}]"""

_EXTRACTION_PROMPT = 'Extract personal facts from this message:\n\n"""{message}"""'


class FactExtractor:
    """Uses Claude Haiku to extract structured facts from user messages."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def extract(self, message: str) -> list[Fact]:
        """Extract facts from a single message. Returns empty list on failure."""
        if len(message.strip()) < 10:
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
                max_tokens=512,
            )
            # Strip markdown code fences if Claude wraps the JSON
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]  # drop opening fence line
                cleaned = cleaned.rsplit("```", 1)[0]  # drop closing fence
            data = json.loads(cleaned.strip())
            if not isinstance(data, list):
                return []
            facts = []
            for item in data:
                if isinstance(item, dict) and "category" in item and "content" in item:
                    facts.append(
                        Fact(
                            category=str(item["category"]).lower()[:50],
                            content=str(item["content"])[:500],
                        )
                    )
            return facts
        except (json.JSONDecodeError, Exception) as e:
            logger.debug("Fact extraction failed: %s", e)
            return []


class FactStore:
    """Persists and retrieves facts in SQLite with deduplication."""

    def __init__(self, db: DatabaseManager, embeddings: EmbeddingStore) -> None:
        self._db = db
        self._embeddings = embeddings

    async def upsert(self, user_id: int, facts: list[Fact]) -> None:
        """Insert new facts, skipping near-duplicates already stored."""
        if not facts:
            return
        existing = await self._get_all_content(user_id)
        for fact in facts:
            # Simple dedup: skip if an identical content string already exists
            if fact.content.lower() in existing:
                logger.debug("Fact already known, skipping: %s", fact.content[:60])
                continue
            await self._insert(user_id, fact)
            existing.add(fact.content.lower())

    async def _insert(self, user_id: int, fact: Fact) -> None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO facts (user_id, category, content, confidence)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, fact.category, fact.content, fact.confidence),
            )
            fact_id = cursor.lastrowid
            await conn.commit()

        # Store embedding in background (non-blocking relative to caller)
        try:
            emb_id = await self._embeddings.upsert_embedding(
                user_id, "fact", fact_id, fact.content
            )
            # Back-fill embedding_id on the fact row
            async with self._db.get_connection() as conn:
                await conn.execute(
                    "UPDATE facts SET embedding_id=? WHERE id=?",
                    (emb_id, fact_id),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("Could not embed fact %d: %s", fact_id, e)

    async def _get_all_content(self, user_id: int) -> set[str]:
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                "SELECT content FROM facts WHERE user_id=?",
                (user_id,),
            )
            return {row["content"].lower() for row in rows}

    async def get_for_user(
        self, user_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent facts for a user, newest first."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, category, content, confidence, created_at
                FROM facts WHERE user_id=?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            )
            return [dict(row) for row in rows]

    async def get_by_category(
        self, user_id: int, category: str
    ) -> list[dict[str, Any]]:
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, category, content, confidence
                FROM facts WHERE user_id=? AND category=?
                ORDER BY created_at DESC
                """,
                (user_id, category),
            )
            return [dict(row) for row in rows]

    async def update(
        self,
        user_id: int,
        fact_id: int,
        new_content: str,
        new_category: str | None = None,
    ) -> bool:
        """Update a fact's content (and optionally its category). Returns True if found."""
        async with self._db.get_connection() as conn:
            if new_category:
                cursor = await conn.execute(
                    "UPDATE facts SET content=?, category=?, updated_at=datetime('now') "
                    "WHERE id=? AND user_id=?",
                    (new_content, new_category, fact_id, user_id),
                )
            else:
                cursor = await conn.execute(
                    "UPDATE facts SET content=?, updated_at=datetime('now') "
                    "WHERE id=? AND user_id=?",
                    (new_content, fact_id, user_id),
                )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete(self, user_id: int, fact_id: int) -> bool:
        """Delete a fact by ID. Returns True if a row was deleted."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM facts WHERE id=? AND user_id=?",
                (fact_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def add(self, user_id: int, content: str, category: str = "other") -> int:
        """Manually insert a fact (bypasses extraction). Returns the new fact ID."""
        fact = Fact(category=category, content=content)
        await self._insert(user_id, fact)
        # Retrieve the ID of what was just inserted
        async with self._db.get_connection() as conn:
            row = await conn.execute_fetchall(
                "SELECT id FROM facts WHERE user_id=? AND content=? ORDER BY id DESC LIMIT 1",
                (user_id, content),
            )
            return row[0]["id"] if row else 0


async def extract_and_store_facts(
    user_id: int,
    message: str,
    extractor: FactExtractor,
    store: FactStore,
) -> None:
    """Convenience coroutine — extract then store. Called as a background task."""
    try:
        facts = await extractor.extract(message)
        if facts:
            await store.upsert(user_id, facts)
            logger.debug("Stored %d facts for user %d", len(facts), user_id)
    except Exception as e:
        logger.warning("extract_and_store_facts failed: %s", e)
