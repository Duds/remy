"""Skill loader — read task-type-specific Markdown instructions from config/skills/ (SAD v10 §12).

Design principles:
- Skills are Markdown, not code. Behavioural logic starts here, not in Python.
- Hot-reloadable: read from disk at call time, no deploy needed to tune behaviour.
- Composable: load_skills() merges multiple skills with a separator.
- Local overrides: {name}.local.md appended after base content (gitignored).
- Missing skills return empty string — never raise.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("config/skills")


def load_skill(name: str) -> str:
    """
    Load base + optional local skill file for a given skill name.

    Returns merged string, or empty string if neither file exists.
    Local override ({name}.local.md) is appended after base content.
    Never raises — missing files are silently skipped.
    """
    if not name:
        return ""

    base = SKILLS_DIR / f"{name}.md"
    local = SKILLS_DIR / f"{name}.local.md"

    parts: list[str] = []
    for p in [base, local]:
        if p.exists():
            try:
                parts.append(p.read_text(encoding="utf-8"))
            except OSError as exc:
                logger.warning("Could not read skill file %s: %s", p, exc)

    return "\n\n".join(parts).strip()


def load_skills(names: list[str]) -> str:
    """
    Load and concatenate multiple skills.

    Skills are separated by a horizontal rule for clarity in the context window.
    Missing skills are silently skipped.
    """
    loaded = [load_skill(n) for n in names]
    return "\n\n---\n\n".join(s for s in loaded if s)
