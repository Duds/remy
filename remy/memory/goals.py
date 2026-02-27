"""
Goal extraction and tracking.

GoalExtractor detects user intentions from messages using Claude Haiku.
GoalStore manages the lifecycle of goals in SQLite (active, completed, abandoned).
"""

import json
import logging
from typing import Any

from ..ai.claude_client import ClaudeClient
from ..config import settings
from ..models import Goal
from .database import DatabaseManager
from .embeddings import EmbeddingStore

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM = """You extract goals and intentions from user messages.
Return ONLY a JSON array of objects with "title" and "description" fields.
A goal is something the user wants to achieve, is working on, or explicitly states as an intention.
Phrases like "I want to", "I'm trying to", "my goal is", "I need to", "I'm working on", "I'd like to" signal goals.
If there are no goals, return [].
Keep titles short (under 10 words). Descriptions can be one sentence.
Example: [{"title": "Launch personal AI agent", "description": "User is building remy as a personal second brain"}]"""

_EXTRACTION_PROMPT = 'Extract goals/intentions from this message:\n\n"""{message}"""'

# Trigger phrases that strongly indicate a goal
_GOAL_TRIGGERS = [
    "i want to", "i'd like to", "i would like to",
    "i'm trying to", "i am trying to",
    "my goal is", "my aim is", "my objective is",
    "i need to", "i plan to", "i intend to",
    "i'm working on", "i am working on",
    "i'm building", "i am building",
    "i hope to", "i'm hoping to",
]


def _message_has_goal_signal(message: str) -> bool:
    lower = message.lower()
    return any(trigger in lower for trigger in _GOAL_TRIGGERS)


class GoalExtractor:
    """Uses Claude Haiku to extract structured goals from user messages."""

    def __init__(self, claude: ClaudeClient) -> None:
        self._claude = claude

    async def extract(self, message: str) -> list[Goal]:
        """Extract goals from a message. Returns [] if no goal signals detected."""
        if not _message_has_goal_signal(message):
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
                cleaned = cleaned.split("\n", 1)[-1]
                cleaned = cleaned.rsplit("```", 1)[0]
            data = json.loads(cleaned.strip())
            if not isinstance(data, list):
                return []
            goals = []
            for item in data:
                if isinstance(item, dict) and "title" in item:
                    goals.append(
                        Goal(
                            title=str(item["title"])[:200],
                            description=str(item.get("description", ""))[:500] or None,
                        )
                    )
            return goals
        except (json.JSONDecodeError, Exception) as e:
            logger.debug("Goal extraction failed: %s", e)
            return []


class GoalStore:
    """Persists and manages goal lifecycle in SQLite."""

    def __init__(self, db: DatabaseManager, embeddings: EmbeddingStore) -> None:
        self._db = db
        self._embeddings = embeddings

    async def upsert(self, user_id: int, goals: list[Goal]) -> None:
        """Insert new goals, skipping near-duplicates based on title similarity."""
        if not goals:
            return
        existing_titles = await self._get_active_titles(user_id)
        for goal in goals:
            title_lower = goal.title.lower()
            # Simple dedup: skip if title already exists (case-insensitive)
            if any(title_lower in existing.lower() or existing.lower() in title_lower
                   for existing in existing_titles):
                logger.debug("Goal already tracked, skipping: %s", goal.title)
                continue
            await self._insert(user_id, goal)
            existing_titles.add(goal.title)

    async def _insert(self, user_id: int, goal: Goal) -> None:
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO goals (user_id, title, description, status)
                VALUES (?, ?, ?, 'active')
                """,
                (user_id, goal.title, goal.description),
            )
            goal_id = cursor.lastrowid
            await conn.commit()

        embed_text = f"{goal.title}. {goal.description or ''}"
        try:
            emb_id = await self._embeddings.upsert_embedding(
                user_id, "goal", goal_id, embed_text
            )
            async with self._db.get_connection() as conn:
                await conn.execute(
                    "UPDATE goals SET embedding_id=? WHERE id=?",
                    (emb_id, goal_id),
                )
                await conn.commit()
        except Exception as e:
            logger.warning("Could not embed goal %d: %s", goal_id, e)

    async def _get_active_titles(self, user_id: int) -> set[str]:
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                "SELECT title FROM goals WHERE user_id=? AND status='active'",
                (user_id,),
            )
            return {row["title"] for row in rows}

    async def get_active(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Return active goals, newest first."""
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT id, title, description, status, created_at
                FROM goals WHERE user_id=? AND status='active'
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            )
            return [dict(row) for row in rows]

    async def mark_complete(self, user_id: int, goal_id: int) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE goals SET status='completed', updated_at=datetime('now') WHERE id=? AND user_id=?",
                (goal_id, user_id),
            )
            await conn.commit()

    async def mark_abandoned(self, user_id: int, goal_id: int) -> None:
        async with self._db.get_connection() as conn:
            await conn.execute(
                "UPDATE goals SET status='abandoned', updated_at=datetime('now') WHERE id=? AND user_id=?",
                (goal_id, user_id),
            )
            await conn.commit()

    async def update(
        self,
        user_id: int,
        goal_id: int,
        new_title: str | None = None,
        new_description: str | None = None,
    ) -> bool:
        """Update a goal's title and/or description. Returns True if found."""
        if not new_title and new_description is None:
            return False
        async with self._db.get_connection() as conn:
            if new_title and new_description is not None:
                cursor = await conn.execute(
                    "UPDATE goals SET title=?, description=?, updated_at=datetime('now') "
                    "WHERE id=? AND user_id=?",
                    (new_title, new_description, goal_id, user_id),
                )
            elif new_title:
                cursor = await conn.execute(
                    "UPDATE goals SET title=?, updated_at=datetime('now') "
                    "WHERE id=? AND user_id=?",
                    (new_title, goal_id, user_id),
                )
            else:
                cursor = await conn.execute(
                    "UPDATE goals SET description=?, updated_at=datetime('now') "
                    "WHERE id=? AND user_id=?",
                    (new_description, goal_id, user_id),
                )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete(self, user_id: int, goal_id: int) -> bool:
        """Permanently delete a goal row. Returns True if a row was deleted."""
        async with self._db.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM goals WHERE id=? AND user_id=?",
                (goal_id, user_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def add(
        self, user_id: int, title: str, description: str | None = None
    ) -> int:
        """Manually add a goal (bypasses extraction). Returns the new goal ID."""
        goal = Goal(title=title[:200], description=description)
        await self._insert(user_id, goal)
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                "SELECT id FROM goals WHERE user_id=? AND title=? ORDER BY id DESC LIMIT 1",
                (user_id, title),
            )
            return rows[0]["id"] if rows else 0


async def extract_and_store_goals(
    user_id: int,
    message: str,
    extractor: GoalExtractor,
    store: GoalStore,
) -> None:
    """Convenience coroutine — extract then store. Called as a background task."""
    try:
        goals = await extractor.extract(message)
        if goals:
            await store.upsert(user_id, goals)
            logger.debug("Stored %d goals for user %d", len(goals), user_id)
    except Exception as e:
        logger.warning("extract_and_store_goals failed: %s", e)
