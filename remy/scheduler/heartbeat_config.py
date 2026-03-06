"""Load and merge HEARTBEAT.md + HEARTBEAT.local.md for evaluative heartbeat.

SAD v7: public template (committed) + optional local overrides (gitignored).
If HEARTBEAT.local.md is missing, the heartbeat runs on public defaults only.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

HEARTBEAT_OK_RESPONSE = "HEARTBEAT_OK"


def load_heartbeat_config() -> str:
    """Load and merge HEARTBEAT.md with HEARTBEAT.local.md.

    Returns:
        Merged markdown string for use as system/instruction context.
    """
    public_path = Path(settings.heartbeat_md_path)
    local_path = public_path.parent / (public_path.stem + ".local" + public_path.suffix)

    if not public_path.exists():
        logger.warning("HEARTBEAT.md not found at %s — heartbeat will use minimal context", public_path)
        return "Respond with HEARTBEAT_OK if nothing warrants contacting the user.\n"

    public_text = public_path.read_text(encoding="utf-8")

    if local_path.exists():
        try:
            local_text = local_path.read_text(encoding="utf-8")
            merged = public_text.rstrip() + "\n\n---\n\n## Local overrides\n\n" + local_text
            logger.debug("Merged HEARTBEAT.md with HEARTBEAT.local.md")
            return merged
        except OSError as e:
            logger.warning("Could not read HEARTBEAT.local.md: %s — using public only", e)
    else:
        logger.debug("No HEARTBEAT.local.md — using public HEARTBEAT.md only")

    return public_text
