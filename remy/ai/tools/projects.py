"""Project tracking tool executors."""

from __future__ import annotations

import logging
from datetime import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_set_project(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Set a project directory to track."""
    from ...ai.input_validator import sanitize_file_path
    from ...config import settings

    path_arg = inp.get("path", "").strip()
    if not path_arg:
        return "Please provide a project path."

    sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
    if err or sanitized is None:
        return f"Invalid path: {err}"

    p = Path(sanitized)
    if not p.exists():
        return f"Path does not exist: {sanitized}"
    if not p.is_dir():
        return f"Path is not a directory: {sanitized}"

    if registry._fact_store is None and registry._knowledge_store is None:
        return "Memory not available — cannot store project."

    if registry._knowledge_store is not None:
        await registry._knowledge_store.add(
            user_id=user_id,
            entity_type="fact",
            content=sanitized,
            metadata={"category": "project"},
        )
    elif registry._fact_store is not None:
        from ...models import Fact
        fact = Fact(category="project", content=sanitized)
        await registry._fact_store.upsert(user_id, [fact])

    return f"✅ Project set: {sanitized}"


async def exec_get_project_status(registry: ToolRegistry, user_id: int) -> str:
    """Get status of tracked projects."""
    if registry._fact_store is None and registry._knowledge_store is None:
        return "Memory not available."

    if registry._knowledge_store is not None:
        items = await registry._knowledge_store.query(
            user_id=user_id,
            entity_type="fact",
            metadata_filter={"category": "project"},
            limit=20,
        )
        facts = [{"content": i.get("content", "")} for i in items]
    elif registry._fact_store is not None:
        facts = await registry._fact_store.get_by_category(user_id, "project")
    else:
        facts = []

    if not facts:
        return "No projects tracked yet. Tell me about a project to track it."

    lines = ["📁 Tracked projects:\n"]
    for f in facts:
        path = f.get("content", "")
        p = Path(path)
        if p.is_dir():
            try:
                all_files = [x for x in p.rglob("*") if x.is_file()]
                file_count = len(all_files)
                if all_files:
                    latest = max(x.stat().st_mtime for x in all_files)
                    mod_str = _dt.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M")
                    lines.append(f"• {path}\n  {file_count} files, last modified {mod_str}")
                else:
                    lines.append(f"• {path}\n  (empty)")
            except Exception as e:
                logger.debug("Failed to get project stats for %s: %s", path, e)
                lines.append(f"• {path}")
        else:
            lines.append(f"• {path} _(not found)_")

    return "\n".join(lines)
