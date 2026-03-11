#!/usr/bin/env python3
"""
One-time migration: export knowledge table rows into PARA items.yaml files.

Groups by entity_type and optionally by entity id derived from metadata.
Creates data/para/areas/people/, projects/, etc. and writes items.yaml per entity.

Usage:
  python scripts/migrate_knowledge_to_para.py [--dry-run]

Requires: data dir with existing SQLite DB (e.g. data/remy.db).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Ensure remy is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remy.config import get_settings
from remy.memory.database import DatabaseManager
from remy.memory.para import PARAStore, PARA_ENTITY_TYPES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = "".join(c if c.isalnum() or c in " -" else "" for c in s)
    s = "-".join(s.split()).strip("-")
    return s[:80] or "unnamed"


async def run(dry_run: bool = False) -> None:
    get_settings()
    db_path = os.environ.get("REMY_DB_PATH") or os.path.join(
        os.environ.get("REMY_DATA_DIR", "data"), "remy.db"
    )
    if not os.path.isfile(db_path):
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    db = DatabaseManager(db_path=db_path)
    await db.init()
    store = PARAStore()

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, user_id, entity_type, content, metadata, created_at
            FROM knowledge
            WHERE superseded_by IS NULL OR superseded_by = ''
            ORDER BY entity_type, created_at
            """
        )
        rows = await cursor.fetchall()

    # Group by (entity_type, entity_id). Use entity_type as bucket; entity_id from metadata or "general"
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        row_id, user_id, entity_type, content, metadata, created_at = row
        # Map DB entity_type to PARA type if possible
        para_type = "areas_people" if entity_type == "fact" else entity_type
        if para_type not in PARA_ENTITY_TYPES:
            para_type = "resources"
        # Use a single "migrated" folder per type for simplicity
        entity_id = "migrated"
        key = (para_type, entity_id)
        if key not in buckets:
            buckets[key] = []
        buckets[key].append({
            "id": f"k{row_id}",
            "content": (content or "")[:2000],
            "status": "active",
            "created_at": created_at or "",
        })

    for (entity_type, entity_id), items in buckets.items():
        if dry_run:
            logger.info("Would create %s/%s with %d items", entity_type, entity_id, len(items))
            continue
        store._ensure_entity_dir(entity_type, entity_id)
        path = store._entity_path(entity_type, entity_id, "items.yaml")
        try:
            import yaml
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(items, f, default_flow_style=False, allow_unicode=True)
            # Write a simple summary
            summary_path = store._entity_path(entity_type, entity_id, "summary.md")
            bullets = [f"- {i.get('content', '')[:150]}" for i in items[-10:]]
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write("\n".join(bullets))
            logger.info("Wrote %s (%d items)", path, len(items))
        except Exception as e:
            logger.error("Failed %s/%s: %s", entity_type, entity_id, e)

    await db.close()
    logger.info("Migration complete.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate knowledge table to PARA files")
    ap.add_argument("--dry-run", action="store_true", help="Only log what would be done")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
