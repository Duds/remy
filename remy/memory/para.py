"""
PARA memory — file-based Projects, Areas, Resources, Archives hierarchy.

Entity folders contain summary.md (quick reference) and items.yaml (atomic facts).
Daily notes go to memory/YYYY-MM-DD.md; tacit knowledge to MEMORY.md (US-para-memory).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import settings

logger = logging.getLogger(__name__)

# Entity types and their directory names under para/
PARA_ENTITY_TYPES = {
    "projects": "projects",
    "areas_people": "areas/people",
    "areas_companies": "areas/companies",
    "resources": "resources",
    "archives": "archives",
}


def _slug(name: str) -> str:
    """Turn a name into a folder-safe slug."""
    s = re.sub(r"[^\w\s-]", "", name.lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return s or "unnamed"


class PARAStore:
    """File-based PARA memory hierarchy."""

    def __init__(self, base_path: str | None = None) -> None:
        self._base = (
            base_path
            or (settings.para_home_path or os.path.join(settings.data_dir, "para"))
        )
        self._memory_dir = os.path.join(os.path.dirname(self._base), "memory")
        self._tacit_path = os.path.join(os.path.dirname(self._base), "MEMORY.md")

    def _entity_dir(self, entity_type: str, entity_id: str) -> str:
        """Path to entity folder (e.g. para/areas/people/john-smith)."""
        sub = PARA_ENTITY_TYPES.get(entity_type, entity_type)
        return os.path.join(self._base, sub, entity_id)

    def _entity_path(self, entity_type: str, entity_id: str, filename: str) -> str:
        return os.path.join(self._entity_dir(entity_type, entity_id), filename)

    def _ensure_entity_dir(self, entity_type: str, entity_id: str) -> None:
        Path(self._entity_dir(entity_type, entity_id)).mkdir(
            parents=True, exist_ok=True
        )

    def get_summary(self, entity_type: str, entity_id: str) -> str | None:
        """Load summary.md for an entity. Returns None if missing."""
        path = self._entity_path(entity_type, entity_id, "summary.md")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning("PARA get_summary %s/%s: %s", entity_type, entity_id, e)
            return None

    def get_items(self, entity_type: str, entity_id: str) -> list[dict]:
        """Load items.yaml for an entity. Returns list of fact dicts."""
        path = self._entity_path(entity_type, entity_id, "items.yaml")
        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            return []
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.warning("PARA get_items %s/%s: %s", entity_type, entity_id, e)
            return []

    def add_fact(
        self,
        entity_type: str,
        entity_id: str,
        fact: str,
        *,
        fact_id: str | None = None,
    ) -> None:
        """Append a fact to the entity's items.yaml."""
        self._ensure_entity_dir(entity_type, entity_id)
        path = self._entity_path(entity_type, entity_id, "items.yaml")
        items = self.get_items(entity_type, entity_id)
        entry = {
            "id": fact_id or f"f{len(items) + 1}",
            "content": fact[:2000],
            "status": "active",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        items.append(entry)
        try:
            import yaml

            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(items, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            logger.error("PARA add_fact write %s: %s", path, e)
            raise

    def supersede_fact(
        self,
        entity_type: str,
        entity_id: str,
        fact_id: str,
        replacement: str,
    ) -> None:
        """Mark a fact as superseded and append the replacement."""
        items = self.get_items(entity_type, entity_id)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for item in items:
            if isinstance(item, dict) and item.get("id") == fact_id:
                item["status"] = "superseded"
                item["superseded_by"] = replacement[:2000]
                item["superseded_at"] = now
                break
        path = self._entity_path(entity_type, entity_id, "items.yaml")
        try:
            import yaml
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(items, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            logger.error("PARA supersede_fact write %s: %s", path, e)
            raise
        self.add_fact(entity_type, entity_id, replacement)

    def append_daily_note(self, content: str) -> None:
        """Append to today's daily notes file (memory/YYYY-MM-DD.md)."""
        Path(self._memory_dir).mkdir(parents=True, exist_ok=True)
        try:
            tz_name = getattr(settings, "scheduler_timezone", "Australia/Sydney")
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        today = datetime.now(tz).strftime("%Y-%m-%d")
        path = os.path.join(self._memory_dir, f"{today}.md")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\n{content.strip()}\n")
        logger.debug("PARA daily note appended: %s", path)

    def rewrite_summary(self, entity_type: str, entity_id: str) -> None:
        """Rewrite summary.md from top active items (e.g. weekly job)."""
        items = [
            i
            for i in self.get_items(entity_type, entity_id)
            if isinstance(i, dict) and i.get("status") != "superseded"
        ]
        items = items[-10:]  # top 10 most recent
        if not items:
            return
        bullets = [
            f"- {i.get('content', '')[:200]}"
            for i in reversed(items)
        ]
        summary = "\n".join(bullets)
        path = self._entity_path(entity_type, entity_id, "summary.md")
        self._ensure_entity_dir(entity_type, entity_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(summary)
        logger.debug("PARA rewrite_summary %s/%s", entity_type, entity_id)

    def find_entity(self, name: str) -> tuple[str, str] | None:
        """Fuzzy match name to an entity folder. Returns (entity_type, entity_id) or None."""
        slug = _slug(name)
        if not slug:
            return None
        for type_key, sub in PARA_ENTITY_TYPES.items():
            dir_path = os.path.join(self._base, sub)
            if not os.path.isdir(dir_path):
                continue
            for candidate in os.listdir(dir_path):
                if not os.path.isdir(os.path.join(dir_path, candidate)):
                    continue
                if slug in candidate or candidate in slug:
                    return (type_key, candidate)
                if _slug(candidate) == slug:
                    return (type_key, candidate)
        return None

    def list_entity_ids(self, entity_type: str) -> list[str]:
        """List entity IDs (folder names) for a type."""
        sub = PARA_ENTITY_TYPES.get(entity_type)
        if not sub:
            return []
        dir_path = os.path.join(self._base, sub)
        if not os.path.isdir(dir_path):
            return []
        return [
            d
            for d in os.listdir(dir_path)
            if os.path.isdir(os.path.join(dir_path, d))
        ]

    def get_mentioned_summaries(self, message: str, max_chars: int = 2000) -> str:
        """
        Return concatenated summary.md content for entities mentioned in message.
        Used by MemoryInjector to inject PARA context.
        """
        if not message or not message.strip():
            return ""
        seen: set[tuple[str, str]] = set()
        parts = []
        total = 0
        # Check each word-like token for entity match
        words = re.findall(r"\b\w+\b", message.lower())
        for i, w in enumerate(words):
            if total >= max_chars:
                break
            # Try single word and 2-word phrase
            phrase = w
            if i + 1 < len(words):
                phrase2 = f"{w}-{words[i+1]}"
            else:
                phrase2 = w
            for candidate in (phrase, phrase2):
                key = self.find_entity(candidate)
                if key and key not in seen:
                    seen.add(key)
                    entity_type, entity_id = key
                    summary = self.get_summary(entity_type, entity_id)
                    if summary and total + len(summary) <= max_chars:
                        parts.append(f"<para_entity id='{entity_id}'>\n{summary}\n</para_entity>")
                        total += len(summary)
        return "\n".join(parts) if parts else ""
