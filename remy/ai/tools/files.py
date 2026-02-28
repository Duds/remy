"""File operation tool executors."""

from __future__ import annotations

import asyncio
import glob as glob_module
import logging
import os
import time
from datetime import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING

from ...config import settings

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


def _sanitize_path(raw: str) -> tuple[str | None, str | None]:
    """Expand ~ and validate path is within allowed base dirs."""
    from ...ai.input_validator import sanitize_file_path
    expanded = str(Path(raw).expanduser())
    path_obj, err = sanitize_file_path(expanded, settings.allowed_base_dirs)
    if err:
        bases = ", ".join(settings.allowed_base_dirs)
        return None, (
            f"{err} "
            f"Valid base directories inside this container are: {bases}. "
            f"Always use ~/Projects/..., ~/Documents/..., or ~/Downloads/... "
            f"(~ expands to {Path.home()} here, not to the host user's home)."
        )
    return path_obj, None


async def exec_read_file(registry: ToolRegistry, inp: dict) -> str:
    """Read the contents of a text file."""
    raw = inp.get("path", "").strip()
    if not raw:
        return "No path provided."

    safe_path, err = _sanitize_path(raw)
    if err or safe_path is None:
        return f"Cannot read file: {err}"

    def _read():
        with open(safe_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    try:
        content = await asyncio.to_thread(_read)
    except FileNotFoundError:
        return f"File not found: {safe_path}"
    except Exception as e:
        return f"Could not read file: {e}"

    if len(content) > 8000:
        content = content[:8000] + f"\n\n[… truncated — {len(content)} chars total]"
    return f"Contents of {safe_path}:\n\n{content}"


async def exec_list_directory(registry: ToolRegistry, inp: dict) -> str:
    """List files and subdirectories at a path."""
    raw = inp.get("path", "").strip()
    if not raw:
        return "No path provided."

    safe_path, err = _sanitize_path(raw)
    if err or safe_path is None:
        return f"Cannot list directory: {err}"

    def _ls():
        p = Path(safe_path)
        if not p.exists():
            return None, f"Path does not exist: {safe_path}"
        if not p.is_dir():
            return None, f"Not a directory: {safe_path}"
        all_entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = []
        for entry in all_entries[:100]:
            prefix = "📁 " if entry.is_dir() else "📄 "
            lines.append(prefix + entry.name)
        suffix = f"\n[…and {len(all_entries) - 100} more entries]" if len(all_entries) > 100 else ""
        return lines, suffix

    try:
        result = await asyncio.to_thread(_ls)
    except Exception as e:
        return f"Could not list directory: {e}"

    lines, suffix = result
    if lines is None:
        return suffix
    return f"Contents of {safe_path}/ ({len(lines)} items):\n" + "\n".join(lines) + (suffix or "")


async def exec_write_file(registry: ToolRegistry, inp: dict) -> str:
    """Write (create or overwrite) a text file."""
    raw = inp.get("path", "").strip()
    content = inp.get("content", "")
    if not raw:
        return "No path provided."

    safe_path, err = _sanitize_path(raw)
    if err or safe_path is None:
        return f"Cannot write file: {err}"

    def _write():
        p = Path(safe_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p.stat().st_size

    try:
        size = await asyncio.to_thread(_write)
    except Exception as e:
        return f"Could not write file: {e}"

    return (
        f"✅ Written {len(content):,} chars to {safe_path} "
        f"({size:,} bytes on disk)."
    )


async def exec_append_file(registry: ToolRegistry, inp: dict) -> str:
    """Append text to the end of an existing file."""
    raw = inp.get("path", "").strip()
    content = inp.get("content", "")
    if not raw:
        return "No path provided."

    safe_path, err = _sanitize_path(raw)
    if err or safe_path is None:
        return f"Cannot append to file: {err}"

    def _append():
        p = Path(safe_path)
        if p.exists():
            existing = p.read_text(encoding="utf-8")
            sep = "" if (not existing or existing.endswith("\n")) else "\n"
        else:
            sep = ""
        with open(safe_path, "a", encoding="utf-8") as f:
            f.write(sep + content)
        return p.stat().st_size

    try:
        size = await asyncio.to_thread(_append)
    except Exception as e:
        return f"Could not append to file: {e}"

    return (
        f"✅ Appended {len(content):,} chars to {safe_path} "
        f"({size:,} bytes total on disk)."
    )


async def exec_find_files(registry: ToolRegistry, inp: dict) -> str:
    """Search for files by filename pattern (glob) under allowed directories."""
    pattern = inp.get("pattern", "").strip()
    if not pattern:
        return "Please provide a filename pattern (e.g. '*.pdf', 'config*')."

    raw_results = []
    for base in settings.allowed_base_dirs:
        raw_results.extend(glob_module.glob(os.path.join(base, "**", pattern), recursive=True))

    from ...ai.input_validator import sanitize_file_path
    results = []
    for r in raw_results:
        safe, err = sanitize_file_path(r, settings.allowed_base_dirs)
        if safe and not err:
            results.append(safe)
    results = results[:20]

    if not results:
        return f"No files matching '{pattern}' found."

    return f"📂 Files matching '{pattern}':\n\n" + "\n".join(results)


async def exec_scan_downloads(registry: ToolRegistry) -> str:
    """Analyse the ~/Downloads folder."""
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        return "Downloads folder not found."

    try:
        files = [f for f in downloads.iterdir() if f.is_file()]
    except Exception as e:
        return f"Could not scan Downloads: {e}"

    if not files:
        return "✅ Downloads folder is empty."

    now = time.time()
    total_bytes = 0

    _EXTS: list[tuple[frozenset, str, str]] = [
        (frozenset(["jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "svg"]), "🖼", "Images"),
        (frozenset(["mp4", "mov", "avi", "mkv", "m4v", "wmv", "flv"]), "🎥", "Videos"),
        (frozenset(["mp3", "m4a", "wav", "flac", "aac", "ogg"]), "🎵", "Audio"),
        (frozenset(["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "pages", "numbers", "key"]), "📄", "Documents"),
        (frozenset(["zip", "tar", "gz", "bz2", "7z", "rar", "dmg", "pkg", "iso"]), "📦", "Archives"),
        (frozenset(["py", "js", "ts", "java", "cpp", "c", "h", "go", "rs", "sh", "json", "yaml", "yml", "toml"]), "💻", "Code"),
    ]

    def _classify(ext: str) -> tuple[str, str]:
        ext = ext.lower().lstrip(".")
        for exts, icon, label in _EXTS:
            if ext in exts:
                return icon, label
        return "📁", "Other"

    def _fmt_bytes(b: int) -> str:
        if b < 1024:
            return f"{b}B"
        if b < 1024 * 1024:
            return f"{b // 1024}KB"
        if b < 1024 ** 3:
            return f"{b // (1024 * 1024)}MB"
        return f"{b / (1024 ** 3):.1f}GB"

    type_counts: dict[str, tuple[str, int, int]] = {}
    age_buckets = {"Today (<1d)": 0, "This week (<7d)": 0, "This month (<30d)": 0, "Old (>30d)": 0}
    oldest: list[tuple[float, str, int]] = []

    for f in files:
        stat = f.stat()
        total_bytes += stat.st_size
        icon, label = _classify(f.suffix)
        prev = type_counts.get(label, (icon, 0, 0))
        type_counts[label] = (icon, prev[1] + 1, prev[2] + stat.st_size)
        age = now - stat.st_mtime
        if age < 86400:
            age_buckets["Today (<1d)"] += 1
        elif age < 7 * 86400:
            age_buckets["This week (<7d)"] += 1
        elif age < 30 * 86400:
            age_buckets["This month (<30d)"] += 1
        else:
            age_buckets["Old (>30d)"] += 1
        oldest.append((stat.st_mtime, f.name, stat.st_size))

    lines = [f"📦 Downloads Scan — {len(files)} files ({_fmt_bytes(total_bytes)} total)\n"]

    lines.append("Type breakdown:")
    for label, (icon, count, nbytes) in sorted(type_counts.items(), key=lambda x: -x[1][2]):
        lines.append(f"  {icon} {label}: {count} file(s), {_fmt_bytes(nbytes)}")

    lines.append("\nAge breakdown:")
    for bucket, count in age_buckets.items():
        if count:
            suffix = " — consider cleanup" if "Old" in bucket else ""
            lines.append(f"  • {bucket}: {count} file(s){suffix}")

    oldest_sorted = sorted(oldest, key=lambda x: x[0])[:8]
    if oldest_sorted:
        lines.append("\nOldest files:")
        for mtime, name, nbytes in oldest_sorted:
            age_days = int((now - mtime) / 86400)
            lines.append(f"  • {name} ({age_days}d old, {_fmt_bytes(nbytes)})")

    return "\n".join(lines)


async def exec_organize_directory(registry: ToolRegistry, inp: dict) -> str:
    """Analyse a directory and suggest how to organise its files into folders."""
    path_arg = inp.get("path", "").strip()
    if not path_arg:
        return "Please provide a directory path."

    safe_path, err = _sanitize_path(path_arg)
    if err or safe_path is None:
        return f"Invalid path: {err}"

    p = Path(safe_path)
    if not p.is_dir():
        return "Not a directory."

    try:
        entries = sorted([f.name for f in p.iterdir()])
    except Exception as e:
        return f"Could not list directory: {e}"

    if not entries:
        return "Directory is empty."

    if registry._claude_client is None:
        return "Claude not available for organisation suggestions."

    listing = "\n".join(entries[:50])
    try:
        suggestions = await registry._claude_client.complete(
            messages=[{
                "role": "user",
                "content": (
                    f"Here is the contents of directory '{safe_path}':\n\n{listing}\n\n"
                    "Suggest how to organise these files. "
                    "Recommend folder names and which files should go where. "
                    "Be specific and actionable."
                ),
            }],
            system="You are a helpful file organisation assistant. Be concise and practical.",
            max_tokens=1024,
        )
        return f"📁 Organisation suggestions for {p.name}:\n\n{suggestions}"
    except Exception as e:
        return f"Could not generate suggestions: {e}"


async def exec_clean_directory(registry: ToolRegistry, inp: dict) -> str:
    """Analyse files in a directory and suggest DELETE, ARCHIVE, or KEEP for each."""
    path_arg = inp.get("path", "").strip()
    if not path_arg:
        return "Please provide a directory path."

    safe_path, err = _sanitize_path(path_arg)
    if err or safe_path is None:
        return f"Invalid path: {err}"

    p = Path(safe_path)
    if not p.is_dir():
        return "Not a directory."

    try:
        files = sorted([f for f in p.iterdir() if f.is_file()], key=lambda x: x.stat().st_mtime)
    except Exception as e:
        return f"Could not list directory: {e}"

    if not files:
        return "No files in directory."

    if registry._claude_client is None:
        return "Claude not available for cleanup suggestions."

    now = time.time()
    file_lines = []
    for f in files[:30]:
        stat = f.stat()
        age_days = int((now - stat.st_mtime) / 86400)
        size_kb = stat.st_size // 1024
        file_lines.append(f"• {f.name} ({size_kb}KB, {age_days}d old)")
    listing = "\n".join(file_lines)

    try:
        suggestions = await registry._claude_client.complete(
            messages=[{
                "role": "user",
                "content": (
                    f"Review these files from '{safe_path}' and suggest DELETE, ARCHIVE, or KEEP for each:\n\n{listing}\n\n"
                    "Format your response as:\n"
                    "• filename.ext — KEEP/ARCHIVE/DELETE — brief reason"
                ),
            }],
            system="You are a helpful file cleanup assistant. Be decisive and practical.",
            max_tokens=1024,
        )
        return f"🗑 Cleanup suggestions for {p.name}:\n\n{suggestions}"
    except Exception as e:
        return f"Could not generate suggestions: {e}"


async def exec_search_files(registry: ToolRegistry, inp: dict) -> str:
    """Search indexed files for content matching a query."""
    if registry._file_indexer is None:
        return (
            "File indexing not available. "
            "The file index may not be configured or enabled."
        )

    if not registry._file_indexer.enabled:
        return "File indexing is disabled in configuration."

    query = inp.get("query", "").strip()
    if not query:
        return "No search query provided."

    limit = min(int(inp.get("limit", 5)), 10)
    path_filter = inp.get("path_filter", "").strip() or None

    try:
        results = await registry._file_indexer.search(
            query, limit=limit, path_filter=path_filter
        )
    except Exception as e:
        return f"Search failed: {e}"

    if not results:
        msg = f"No files found matching '{query}'."
        if path_filter:
            msg += f" (searched in {path_filter})"
        return msg

    lines = [f"📂 File search results for \"{query}\":"]
    lines.append("")

    for i, result in enumerate(results, 1):
        path = result.get("path", "unknown")
        chunk_idx = result.get("chunk_index", 0)
        content = result.get("content_text", "")

        if len(content) > 200:
            content = content[:200] + "…"

        content = content.replace("\n", " ").strip()

        lines.append(f"{i}. {path} (chunk {chunk_idx})")
        lines.append(f"   \"{content}\"")
        lines.append("")

    lines.append("Use read_file to see the full content of any file.")
    return "\n".join(lines)


async def exec_index_status(registry: ToolRegistry) -> str:
    """Show the current state of the file index."""
    if registry._file_indexer is None:
        return (
            "File indexing not available. "
            "The file index may not be configured."
        )

    if not registry._file_indexer.enabled:
        return "File indexing is disabled in configuration."

    try:
        status = await registry._file_indexer.get_status()
    except Exception as e:
        return f"Could not get index status: {e}"

    ext_list = status.extensions[:8]
    ext_str = ", ".join(ext_list)
    if len(status.extensions) > 8:
        ext_str += f" (+{len(status.extensions) - 8} more)"

    paths_str = "\n  ".join(status.paths) if status.paths else "None configured"

    last_run = status.last_run or "Never"

    return (
        f"📂 File index status:\n"
        f"  Paths:\n  {paths_str}\n"
        f"  Files indexed: {status.files_indexed:,}\n"
        f"  Total chunks: {status.total_chunks:,}\n"
        f"  Last indexed: {last_run}\n"
        f"  Extensions: {ext_str}"
    )
