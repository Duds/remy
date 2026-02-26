"""
Memory injector — builds the <memory> XML block injected into Claude's system prompt.

Retrieves:
  - Top-5 semantically similar facts (ANN) or top-5 FTS keyword matches (fallback)
  - Top-3 active goals
  - Formats as XML block appended after SOUL.md
"""

import logging
from pathlib import Path
from typing import Any

from .database import DatabaseManager
from .embeddings import EmbeddingStore
from .facts import FactStore
from .fts import FTSSearch
from .goals import GoalStore

logger = logging.getLogger(__name__)


class MemoryInjector:
    """Builds a memory context block for injection into Claude's system prompt."""

    def __init__(
        self,
        db: DatabaseManager,
        embeddings: EmbeddingStore,
        fact_store: FactStore,
        goal_store: GoalStore,
        fts: FTSSearch,
    ) -> None:
        self._db = db
        self._embeddings = embeddings
        self._facts = fact_store
        self._goals = goal_store
        self._fts = fts

    async def build_context(self, user_id: int, current_message: str) -> str:
        """
        Return a memory XML block to append to the system prompt.
        Returns empty string if no memory is available.
        """
        facts = await self._get_relevant_facts(user_id, current_message)
        project_ctx = await self._get_project_context(user_id)
        goals = await self._get_active_goals(user_id, current_message)

        all_facts = facts + project_ctx
        if not all_facts and not goals:
            return ""

        parts = ["<memory>"]

        if all_facts:
            parts.append("  <facts>")
            for f in all_facts:
                category = f.get("category", "general")
                content = f.get("content", "")
                parts.append(f"    <fact category='{category}'>{content}</fact>")
            parts.append("  </facts>")

        if goals:
            parts.append("  <goals>")
            for g in goals:
                title = g.get("title", "")
                desc = g.get("description") or ""
                suffix = f" — {desc}" if desc else ""
                parts.append(f"    <goal>{title}{suffix}</goal>")
            parts.append("  </goals>")

        parts.append("</memory>")
        return "\n".join(parts)

    async def _get_relevant_facts(
        self, user_id: int, query: str
    ) -> list[dict[str, Any]]:
        """Try ANN search, fall back to FTS5, fall back to recent facts."""
        # Try ANN vector search
        ann_results = await self._embeddings.search_similar_for_type(
            user_id, query, source_type="fact", limit=5
        )
        if ann_results:
            # Resolve source_ids back to full fact rows
            fact_ids = [r["source_id"] for r in ann_results if r.get("source_id")]
            if fact_ids:
                return await self._facts_by_ids(user_id, fact_ids)

        # Fall back to FTS5 keyword search
        fts_results = await self._fts.search_facts(user_id, query, limit=5)
        if fts_results:
            return fts_results

        # Final fallback: most recent facts
        return await self._facts.get_for_user(user_id, limit=5)

    async def _get_active_goals(
        self, user_id: int, query: str
    ) -> list[dict[str, Any]]:
        """Try ANN search for goals, fall back to all active goals."""
        ann_results = await self._embeddings.search_similar_for_type(
            user_id, query, source_type="goal", limit=3
        )
        if ann_results:
            goal_ids = [r["source_id"] for r in ann_results if r.get("source_id")]
            if goal_ids:
                return await self._goals_by_ids(user_id, goal_ids)

        # Fall back to FTS
        fts_results = await self._fts.search_goals(user_id, query, limit=3)
        if fts_results:
            return fts_results

        return await self._goals.get_active(user_id, limit=3)

    async def _get_project_context(self, user_id: int) -> list[dict[str, Any]]:
        """
        Read README.md from tracked project directories and return as project_context facts.
        Caps at 1500 chars per project, max 3 projects.
        """
        try:
            project_facts = await self._facts.get_by_category(user_id, "project")
        except Exception:
            return []
        if not project_facts:
            return []
        results = []
        for pf in project_facts[:3]:
            project_path = pf.get("content", "")
            readme = Path(project_path) / "README.md"
            if readme.exists():
                try:
                    content = readme.read_text(encoding="utf-8")[:1500]
                    results.append({
                        "category": "project_context",
                        "content": f"[{project_path}] {content}",
                    })
                except Exception:
                    pass
        return results

    async def _facts_by_ids(
        self, user_id: int, fact_ids: list[int]
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" * len(fact_ids))
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT id, category, content, confidence FROM facts "
                f"WHERE user_id=? AND id IN ({placeholders})",
                (user_id, *fact_ids),
            )
            return [dict(row) for row in rows]

    async def _goals_by_ids(
        self, user_id: int, goal_ids: list[int]
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" * len(goal_ids))
        async with self._db.get_connection() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT id, title, description, status FROM goals "
                f"WHERE user_id=? AND id IN ({placeholders}) AND status='active'",
                (user_id, *goal_ids),
            )
            return [dict(row) for row in rows]

    async def build_system_prompt(
        self, user_id: int, current_message: str, soul_md: str
    ) -> str:
        """Return the full system prompt: SOUL.md + memory block."""
        memory_block = await self.build_context(user_id, current_message)
        if memory_block:
            return f"{soul_md}\n\n{memory_block}"
        return soul_md
