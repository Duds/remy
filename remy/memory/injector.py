"""
Memory injector — builds the <memory> XML block injected into Claude's system prompt.

Retrieves:
  - Top-5 semantically similar facts (ANN) or top-5 FTS keyword matches (fallback)
  - Top-3 active goals
  - Emotional context (health issues, stressors, deadlines) for tone-aware responses
  - Formats as XML block appended after SOUL.md
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .database import DatabaseManager
from .embeddings import EmbeddingStore
from .fts import FTSSearch
from .knowledge import KnowledgeStore
from ..models import EmotionalTone, KnowledgeItem

if TYPE_CHECKING:
    from ..ai.tone import ToneDetector

logger = logging.getLogger(__name__)


class MemoryInjector:
    """Builds a memory context block for injection into Claude's system prompt."""

    def __init__(
        self,
        db: DatabaseManager,
        embeddings: EmbeddingStore,
        knowledge_store: KnowledgeStore,
        fts: FTSSearch,
        tone_detector: "ToneDetector | None" = None,
    ) -> None:
        self._db = db
        self._embeddings = embeddings
        self._knowledge = knowledge_store
        self._fts = fts
        self._tone_detector = tone_detector

    async def build_context(
        self,
        user_id: int,
        current_message: str,
        min_confidence: float = 0.5,
        emotional_tone: EmotionalTone | None = None,
        local_hour: int | None = None,
    ) -> str:
        """
        Return a memory XML block to append to the system prompt.
        Returns empty string if no memory is available.

        Args:
            min_confidence: Only include knowledge items at or above this threshold.
                            Defaults to 0.5 to exclude speculative extractions.
            emotional_tone: Pre-detected emotional tone (if None, will detect)
            local_hour: Hour in user's local timezone for tone detection
        """
        # Fetch relevant items in parallel for better latency
        facts_task = self._get_relevant_knowledge(
            user_id, current_message, "fact", limit=5, min_confidence=min_confidence
        )
        goals_task = self._get_relevant_knowledge(
            user_id, current_message, "goal", limit=3, min_confidence=min_confidence
        )
        shopping_task = self._get_relevant_knowledge(
            user_id, current_message, "shopping_item", limit=5, min_confidence=min_confidence
        )
        project_task = self._get_project_context(user_id)

        facts, goals, shopping, project_ctx = await asyncio.gather(
            facts_task, goals_task, shopping_task, project_task
        )
        
        # Detect emotional tone if not provided (lazy - only when needed)
        detected_tone = emotional_tone
        if detected_tone is None and self._tone_detector:
            detected_tone = await self._tone_detector.detect_tone(
                user_id, current_message, local_hour=local_hour
            )
        
        # Get emotional context for tone-aware responses
        emotional_ctx = await self._get_emotional_context(user_id, detected_tone)

        if not facts and not goals and not shopping and not project_ctx and not emotional_ctx:
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

        # Add emotional context block
        if emotional_ctx:
            parts.append("  <emotional_context>")
            if detected_tone:
                parts.append(f"    <detected_tone>{detected_tone.value}</detected_tone>")
            if emotional_ctx.get("health_issues"):
                parts.append("    <health_context>")
                for h in emotional_ctx["health_issues"][:3]:
                    parts.append(f"      <issue>{h['content']}</issue>")
                parts.append("    </health_context>")
            if emotional_ctx.get("upcoming_deadlines"):
                parts.append("    <deadline_pressure>")
                for d in emotional_ctx["upcoming_deadlines"][:3]:
                    parts.append(f"      <deadline>{d['content']}</deadline>")
                parts.append("    </deadline_pressure>")
            if emotional_ctx.get("recent_stressors"):
                parts.append("    <recent_stressors>")
                for s in emotional_ctx["recent_stressors"][:3]:
                    parts.append(f"      <stressor>{s}</stressor>")
                parts.append("    </recent_stressors>")
            parts.append("  </emotional_context>")

        parts.append("</memory>")
        return "\n".join(parts)

    async def _get_emotional_context(
        self, user_id: int, tone: EmotionalTone | None
    ) -> dict[str, Any]:
        """
        Retrieve emotional context relevant to the detected tone.
        
        Only fetches context when tone suggests it's relevant:
        - STRESSED/VULNERABLE: health issues, deadlines, stressors
        - TIRED: health issues
        - NEUTRAL/PLAYFUL/CELEBRATORY: minimal context
        """
        result: dict[str, Any] = {}
        
        # Only fetch detailed context for emotionally charged tones
        if tone not in (EmotionalTone.STRESSED, EmotionalTone.VULNERABLE, 
                        EmotionalTone.TIRED, EmotionalTone.FRUSTRATED):
            return result
        
        try:
            facts = await self._knowledge.get_by_type(
                user_id, "fact", limit=100, min_confidence=0.5
            )
            
            # Health issues (relevant for stressed, vulnerable, tired)
            health_facts = [
                {"content": f.content, "category": f.metadata.get("category")}
                for f in facts
                if f.metadata.get("category") in ("health", "medical")
            ]
            if health_facts:
                result["health_issues"] = health_facts
            
            # Deadlines (relevant for stressed, frustrated)
            if tone in (EmotionalTone.STRESSED, EmotionalTone.FRUSTRATED):
                deadline_facts = [
                    {"content": f.content}
                    for f in facts
                    if f.metadata.get("category") == "deadline"
                ]
                if deadline_facts:
                    result["upcoming_deadlines"] = deadline_facts
            
            # Semantic search for recent stressors
            if tone == EmotionalTone.STRESSED and self._embeddings:
                stress_results = await self._embeddings.search_similar_for_type(
                    user_id,
                    query="stress problem difficulty worry concern",
                    source_type="knowledge_fact",
                    limit=5,
                    recency_boost=True,
                )
                recent_stressors = [
                    r.get("content", "")
                    for r in stress_results
                    if r.get("distance", 1.0) < 0.4 and r.get("content")
                ]
                if recent_stressors:
                    result["recent_stressors"] = recent_stressors
                    
        except Exception as e:
            logger.debug("Failed to get emotional context: %s", e)
        
        return result

    async def _get_relevant_knowledge(
        self, user_id: int, query: str, entity_type: str, limit: int = 5, min_confidence: float = 0.5
    ) -> list:
        """Unified search across ANN, FTS, and recent history for a specific type.
        
        Updates last_referenced_at for any items returned (staleness tracking).
        """
        # Note: types in Knowledge are: fact, goal, shopping_item
        # 1. Try ANN search with recency boost
        ann_results = await self._embeddings.search_similar_for_type(
            user_id, query, source_type=f"knowledge_{entity_type}", limit=limit,
            recency_boost=True
        )
        if ann_results:
            ids = [r["source_id"] for r in ann_results if r.get("source_id")]
            if ids:
                items = await self._get_by_ids(user_id, ids, min_confidence=min_confidence)
                # Update last_referenced_at for returned items
                if items:
                    item_ids = [i.id for i in items if i.id]
                    await self._knowledge.update_last_referenced(user_id, item_ids)
                return items

        # 2. Fall back to FTS (to be updated to unified search)
        # For now, we'll just fall back to recent items
        items = await self._knowledge.get_by_type(user_id, entity_type, limit=limit, min_confidence=min_confidence)
        # Update last_referenced_at for returned items
        if items:
            item_ids = [i.id for i in items if i.id]
            await self._knowledge.update_last_referenced(user_id, item_ids)
        return items

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
                except Exception as e:
                    logger.debug("Failed to read project context file %s: %s", path_str, e)
        return results

    async def build_system_prompt(
        self,
        user_id: int,
        current_message: str,
        soul_md: str,
        min_confidence: float = 0.5,
        emotional_tone: EmotionalTone | None = None,
        local_hour: int | None = None,
    ) -> str:
        """Return the full system prompt: SOUL.md + memory block."""
        from ..utils.tokens import estimate_tokens

        memory_block = await self.build_context(
            user_id,
            current_message,
            min_confidence=min_confidence,
            emotional_tone=emotional_tone,
            local_hour=local_hour,
        )

        if memory_block:
            full_prompt = f"{soul_md}\n\n{memory_block}"
        else:
            full_prompt = soul_md

        # Log token breakdown at DEBUG level
        soul_tokens = estimate_tokens(soul_md)
        memory_tokens = estimate_tokens(memory_block) if memory_block else 0
        total_tokens = estimate_tokens(full_prompt)
        logger.debug(
            "System prompt: %d tokens (soul: %d, memory: %d)",
            total_tokens, soul_tokens, memory_tokens
        )

        return full_prompt
