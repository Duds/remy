"""Configuration audit trail for debugging and compliance.

Logs all configuration values at startup and any runtime changes to a JSONL file.
Sensitive values (API keys, tokens) are redacted.

Inspired by OpenClaw's config-audit.jsonl pattern.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remy.config import Settings

logger = logging.getLogger(__name__)

# Patterns for sensitive keys that should be redacted
_SENSITIVE_PATTERNS = [
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
]


def _is_sensitive(key: str) -> bool:
    """Check if a key name indicates a sensitive value."""
    return any(pattern.match(key) for pattern in _SENSITIVE_PATTERNS)


def _redact(value: Any) -> str:
    """Redact a sensitive value, showing only first/last 4 chars if long enough."""
    s = str(value)
    if len(s) <= 8:
        return "***REDACTED***"
    return f"{s[:4]}...{s[-4:]}"


def _serialize_value(key: str, value: Any) -> str:
    """Serialize a config value, redacting sensitive ones."""
    if _is_sensitive(key) and value:
        return _redact(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


class ConfigAuditor:
    """Audit trail for configuration changes.

    Usage:
        auditor = ConfigAuditor(Path("data/config-audit.jsonl"))
        auditor.log_startup(settings)
        # Later, if config changes at runtime:
        auditor.log_change("MODEL_COMPLEX", old_value, new_value, source="runtime")
    """

    def __init__(self, audit_path: Path | str) -> None:
        self.audit_path = Path(audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def log_startup(self, settings: Settings) -> None:
        """Log all settings at startup (redacting sensitive values)."""
        timestamp = datetime.now(timezone.utc).isoformat()

        # Get all settings as a dict
        settings_dict = {}
        for field_name in settings.model_fields:
            try:
                value = getattr(settings, field_name)
                settings_dict[field_name] = _serialize_value(field_name, value)
            except Exception:
                settings_dict[field_name] = "<error reading value>"

        # Also include computed properties
        for prop_name in ["db_path", "sessions_dir", "logs_dir", "telegram_allowed_users"]:
            try:
                value = getattr(settings, prop_name)
                settings_dict[prop_name] = _serialize_value(prop_name, value)
            except Exception as e:
                logger.debug("Failed to serialize property %s: %s", prop_name, e)

        entry = {
            "timestamp": timestamp,
            "action": "startup",
            "settings": settings_dict,
            "pid": os.getpid(),
        }

        self._write_entry(entry)
        logger.info("Logged startup configuration to %s", self.audit_path)

    def log_change(
        self,
        key: str,
        old_value: Any,
        new_value: Any,
        source: str = "runtime",
    ) -> None:
        """Log a configuration change."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "change",
            "key": key,
            "old_value": _serialize_value(key, old_value) if old_value is not None else None,
            "new_value": _serialize_value(key, new_value),
            "source": source,
        }

        self._write_entry(entry)
        logger.info("Config change logged: %s = %s (source=%s)", key, _serialize_value(key, new_value), source)

    def log_event(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        """Log a generic configuration-related event."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": event_type,
            "details": details or {},
        }
        self._write_entry(entry)

    def get_recent_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read the most recent audit entries."""
        if not self.audit_path.exists():
            return []

        entries = []
        try:
            with open(self.audit_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning("Failed to read audit log: %s", e)
            return []

        return entries[-limit:]

    def _write_entry(self, entry: dict[str, Any]) -> None:
        """Append an entry to the audit log."""
        try:
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error("Failed to write audit entry: %s", e)


# Module-level singleton
_auditor: ConfigAuditor | None = None


def get_auditor(data_dir: str | None = None) -> ConfigAuditor:
    """Get or create the config auditor singleton."""
    global _auditor
    if _auditor is None:
        if data_dir is None:
            from remy.config import settings
            data_dir = settings.data_dir
        _auditor = ConfigAuditor(Path(data_dir) / "config-audit.jsonl")
    return _auditor


def log_startup_config() -> None:
    """Convenience function to log startup configuration."""
    from remy.config import get_settings
    auditor = get_auditor()
    auditor.log_startup(get_settings())
