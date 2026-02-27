"""
Memory injector — builds the <memory> XML block injected into Claude's system prompt.

Retrieves:
  - Top-5 semantically similar facts (ANN) or top-5 FTS keyword matches (fallback)
  - Top-3 active goals
  - Formats as XML block appended after SOUL.md
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from .database import DatabaseManager
from .embeddings import EmbeddingStore
from .fts import FTSSearch
from .knowledge import KnowledgeStore
from ..models import KnowledgeItem

logger = logging.getLogger(__name__)


class MemoryInjector:
    """Builds a memory context block for injection into Claude's system prompt."""

    def __init__(
        self,
        db: DatabaseManager,
        embeddings: EmbeddingStore,
        knowledge_store: KnowledgeStore,
        fts: FTSSearch,
    ) -> None:
        self._db = db
        self._embeddings = embeddings
        self._knowledge = knowledge_store
        self._fts = fts

    async def build_context(
        self, user_id: int, current_message: str, min_confidence: float = 0.5
    ) -> str:
        """
        Return a memory XML block to append to the system prompt.
        Returns empty string if no memory is available.

        Args:
            min_confidence: Only include knowledge items at or above this threshold.
                            Defaults to 0.5 to exclude speculative extractions.
        """
        # Fetch relevant items from the unified store
        facts = await self._get_relevant_knowledge(user_id, current_message, "fact", limit=5, min_confidence=min_confidence)
        goals = await self._get_relevant_knowledge(user_id, current_message, "goal", limit=3, min_confidence=min_confidence)
        shopping = await self._get_relevant_knowledge(user_id, current_message, "shopping_item", limit=5, min_confidence=min_confidence)
        
        project_ctx = await self._get_project_context(user_id)

        if not facts and not goals and not shopping and not project_ctx:
            return ""

        parts = ["<memory>"]

        if facts or project_ctx:
            parts.append("  <facts>")
            for f in facts:
                meta = f.metadata or {}
                category = meta.get("category", "general")
                id_attr = f" id='{f.id}'" if f.id else ""
                parts.append(f"    <fact{id_attr} category='{category}'>{f.content}</fact>")
            for p in project_ctx:
                parts.append(f"    <fact category='project_context'>{p['content']}</fact>")
            parts.append("  </facts>")

        if goals:
            parts.append("  <goals>")
            for g in goals:
                desc = g.metadata.get("description", "")
                suffix = f" — {desc}" if desc else ""
                id_attr = f" id='{g.id}'" if g.id else ""
                parts.append(f"    <goal{id_attr}>{g.content}{suffix}</goal>")
            parts.append("  </goals>")

        if shopping:
            parts.append("  <shopping_list>")
            for i in shopping:
                id_attr = f" id='{i.id}'" if i.id else ""
                parts.append(f"    <item{id_attr}>{i.content}</item>")
            parts.append("  </shopping_list>")

        parts.append("</memory>")
        return "\n".join(parts)

    async def _get_relevant_knowledge(
        self, user_id: int, query: str, entity_type: str, limit: int = 5, min_confidence: float = 0.5
    ) -> list:
        """Unified search across ANN, FTS, and recent history for a specific type."""
        # Note: types in types in Knowledge are: fact, goal, shopping_item
        # 1. Try ANN search
        ann_results = await self._embeddings.search_similar_for_type(
            user_id, query, source_type=f"knowledge_{entity_type}", limit=limit
        )
        if ann_results:
            ids = [r["source_id"] for r in ann_results if r.get("source_id")]
            if ids:
                return await self._get_by_ids(user_id, ids, min_confidence=min_confidence)

        # 2. Fall back to FTS (to be updated to unified search)
        # For now, we'll just fall back to recent items
        return await self._knowledge.get_by_type(user_id, entity_type, limit=limit, min_confidence=min_confidence)

    async def _get_by_ids(self, user_id: int, ids: list[int], min_confidence: float = 0.5) -> list[KnowledgeItem]:
        placeholders = ",".join("?" * len(ids))
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT id, entity_type, content, metadata, confidence FROM knowledge "
                f"WHERE user_id=? AND id IN ({placeholders}) AND confidence >= ?",
                (user_id, *ids, min_confidence),
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

    async def _get_project_context(self, user_id: int) -> list[dict[str, Any]]:
        """
        Read README.md from tracked project directories and return as project_context facts.
        """
        try:
            # Metadata in knowledge table stores category for facts
            async with self._db.get_connection() as conn:
                rows = await conn.execute_fetchall(
                    "SELECT content FROM knowledge WHERE user_id=? AND entity_type='fact' AND metadata LIKE '%\"category\": \"project\"%'",
                    (user_id,)
                )
                project_paths = [row["content"] for row in rows]
        except Exception:
            return []
            
        if not project_paths:
            return []
            
        results = []
        for path_str in project_paths[:3]:
            readme = Path(path_str) / "README.md"
            if readme.exists():
                try:
                    content = await asyncio.to_thread(
                        lambda p: p.read_text(encoding="utf-8"), readme
                    )
                    content = content[:1500]
                    results.append({
                        "category": "project_context",
                        "content": f"[{path_str}] {content}",
                    })
                except Exception:
                    pass
        return results

    async def build_system_prompt(
        self, user_id: int, current_message: str, soul_md: str, min_confidence: float = 0.5
    ) -> str:
        """Return the full system prompt: SOUL.md + memory block."""
        memory_block = await self.build_context(user_id, current_message, min_confidence=min_confidence)
        if memory_block:
            return f"{soul_md}\n\n{memory_block}"
        return soul_md
