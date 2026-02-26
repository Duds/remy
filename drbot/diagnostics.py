"""
Diagnostic utilities for analyzing bot logs and reporting issues.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Log line format: "2026-02-26 14:32:45 [LEVEL] logger.name: message"
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _parse_ts(line: str) -> Optional[datetime]:
    m = _TS_RE.match(line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def since_dt(since: Optional[str]) -> Optional[datetime]:
    """Convert a since string to a datetime cutoff, or None for no filter."""
    if not since or since == "all":
        return None
    if since == "1h":
        return datetime.now() - timedelta(hours=1)
    if since == "6h":
        return datetime.now() - timedelta(hours=6)
    if since == "24h":
        return datetime.now() - timedelta(hours=24)
    # "startup" is handled separately via get_session_start_line
    return None


# Keep the old private name as an alias so tool_registry.py still works
_since_dt = since_dt


def _log_file(data_dir: str) -> Path:
    """Return the path to drbot.log, checking both logs/ subdir and data_dir directly."""
    candidate = Path(data_dir) / "logs" / "drbot.log"
    if candidate.exists():
        return candidate
    return Path(data_dir) / "drbot.log"


def get_session_start_line(data_dir: str) -> int:
    """
    Return the line index (0-based) of the last 'Starting drbot' entry in the log.
    Returns 0 if not found (include everything).

    Using line index rather than timestamp avoids timezone mismatch between
    local Python runs (Sydney time) and Docker container runs (UTC).
    """
    log_file = _log_file(data_dir)
    if not log_file.exists():
        return 0

    result = 0
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if "Starting drbot" in line:
                    result = i  # keep the last (most recent by file position) match
    except Exception:
        pass
    return result


def get_session_start(data_dir: str) -> Optional[datetime]:
    """
    Return the timestamp of the last 'Starting drbot' entry for display purposes only.
    Do not use this for filtering — use get_session_start_line instead.
    """
    log_file = _log_file(data_dir)
    if not log_file.exists():
        return None

    result: Optional[datetime] = None
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if "Starting drbot" in line:
                    ts = _parse_ts(line)
                    if ts is not None:
                        result = ts
    except Exception:
        pass
    return result


def get_recent_logs(
    data_dir: str,
    lines: int = 50,
    level: Optional[str] = None,
    since: Optional[datetime] = None,
    since_line: Optional[int] = None,
) -> str:
    """
    Read recent logs from drbot.log file.

    Args:
        data_dir: Directory containing drbot.log (or logs/ subdir)
        lines: Number of recent lines to return
        level: Filter by log level (e.g., "ERROR", "WARNING")
        since: Only include lines with a timestamp >= this datetime (for relative time filters)
        since_line: Only include lines at or after this file line index (for startup filter)

    Returns:
        Recent log entries as formatted string, or error message if unavailable
    """
    log_file = _log_file(data_dir)

    if not log_file.exists():
        return "No logs available yet (drbot.log not created)"

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        # Filter by file position (startup session filter)
        if since_line is not None:
            all_lines = all_lines[since_line:]

        # Filter by timestamp (relative time filter: 1h/6h/24h)
        if since is not None:
            all_lines = [l for l in all_lines if (_parse_ts(l) or datetime.min) >= since]

        # Filter by level if specified
        if level:
            all_lines = [l for l in all_lines if f"[{level}]" in l]

        # Get the last N lines
        recent = all_lines[-lines:] if len(all_lines) > lines else all_lines

        formatted = "".join(recent)
        return formatted or f"No {level or 'recent'} logs found"

    except Exception as e:
        return f"Error reading logs: {e}"


def get_error_summary(
    data_dir: str,
    max_items: int = 10,
    since: Optional[datetime] = None,
    since_line: Optional[int] = None,
) -> str:
    """
    Analyze logs and return a summary of recent errors.

    Args:
        data_dir: Directory containing drbot.log (or logs/ subdir)
        max_items: Maximum error summaries to return
        since: Only include lines with timestamp >= this datetime (relative time filters)
        since_line: Only include lines at or after this file line index (startup filter)

    Returns:
        Summary of recent errors and warnings
    """
    log_file = _log_file(data_dir)

    if not log_file.exists():
        return "No logs available"

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Filter by file position (startup session filter)
        if since_line is not None:
            lines = lines[since_line:]

        # Filter by timestamp (relative time filters)
        if since is not None:
            lines = [l for l in lines if (_parse_ts(l) or datetime.min) >= since]

        # Find errors and warnings
        errors = [l for l in lines if " [ERROR] " in l]
        warnings = [l for l in lines if " [WARNING] " in l]

        summary = []

        if errors:
            summary.append(f"🚨 **Recent Errors ({len(errors)} total)**")
            for line in errors[-max_items:]:
                if ":" in line:
                    msg = line.split(":", 2)[-1].strip()
                    summary.append(f"  • {msg}")

        if warnings:
            summary.append(f"\n⚠️  **Recent Warnings ({len(warnings)} total)**")
            for line in warnings[-max_items:]:
                if ":" in line:
                    msg = line.split(":", 2)[-1].strip()
                    summary.append(f"  • {msg}")

        scope = f"since {since.strftime('%H:%M:%S')}" if since else "this session"
        return "\n".join(summary) if summary else f"No errors or warnings ({scope})"

    except Exception as e:
        return f"Error analyzing logs: {e}"
