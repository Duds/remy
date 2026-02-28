"""
File operation handlers.

Contains handlers for file reading, writing, listing, searching, and project management.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime as _dt
from pathlib import Path
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from .base import reject_unauthorized, _pending_writes
from ...ai.input_validator import sanitize_file_path
from ...config import settings

if TYPE_CHECKING:
    from ...memory.facts import FactStore

logger = logging.getLogger(__name__)


def make_file_handlers(
    *,
    claude_client=None,
    fact_store: "FactStore | None" = None,
):
    """
    Factory that returns file operation handlers.
    
    Returns a dict of command_name -> handler_function.
    """

    async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/read <path> — return contents of a text file in allowed dirs. Files >50KB are summarised."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /read <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        try:
            fpath = Path(sanitized)
            file_size = fpath.stat().st_size
        except Exception as e:
            await update.message.reply_text(f"❌ Could not read file: {e}")
            return

        _SIZE_50KB = 50 * 1024
        if file_size > _SIZE_50KB and claude_client is not None:
            try:
                with open(sanitized, encoding="utf-8", errors="replace") as f:
                    data = f.read(20000)
            except Exception as e:
                await update.message.reply_text(f"❌ Could not read file: {e}")
                return
            await update.message.reply_text(
                f"📄 `{fpath.name}` is large ({file_size // 1024}KB). Summarising…",
                parse_mode="Markdown",
            )
            try:
                summary = await claude_client.complete(
                    messages=[{
                        "role": "user",
                        "content": f"Summarise this file concisely:\n\n{data}",
                    }],
                    system="You are a file summarisation assistant. Be concise and factual.",
                    max_tokens=512,
                )
                await update.message.reply_text(
                    f"📄 *Summary of {fpath.name}:*\n\n{summary}",
                    parse_mode="Markdown",
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Could not summarise: {e}")
            return

        try:
            with open(sanitized, encoding="utf-8", errors="replace") as f:
                data = f.read()
        except Exception as e:
            await update.message.reply_text(f"❌ Could not read file: {e}")
            return
        if len(data) > 8000:
            data = data[:8000] + "\n...[truncated]"
        await update.message.reply_text(
            ("📄 Contents of %s:\n```\n" +
             "%s\n```") % (sanitized, data),
            parse_mode="Markdown",
        )

    async def write_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/write <path> — prompt user for text to write afterwards."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /write <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        _pending_writes[update.effective_user.id] = sanitized
        await update.message.reply_text(
            f"Send me the text you want to write to {sanitized}."
        )

    async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ls <dir> — list files in a directory under allowed bases."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /ls <directory>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        try:
            entries = os.listdir(sanitized)
            await update.message.reply_text(
                "\n".join(entries) or "(empty directory)"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Could not list directory: {e}")

    async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/find <pattern> — search filenames under allowed bases."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /find <glob-pattern>")
            return
        pattern = context.args[0]
        import glob
        raw_results = []
        for base in settings.allowed_base_dirs:
            raw_results.extend(glob.glob(os.path.join(base, "**", pattern), recursive=True))
        results = []
        for r in raw_results:
            safe, err = sanitize_file_path(r, settings.allowed_base_dirs)
            if safe and not err:
                results.append(safe)
        results = results[:20]
        if not results:
            await update.message.reply_text("No matching files found.")
        else:
            await update.message.reply_text("\n".join(results))

    async def set_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/set-project <path> — remember a project location."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /set_project <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        from ...models import Fact
        fact = Fact(category="project", content=sanitized)
        if fact_store is not None:
            await fact_store.upsert(update.effective_user.id, [fact])
        await update.message.reply_text(f"Project set: {sanitized}")

    async def project_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/project-status — list remembered project paths with file count and last modified."""
        if await reject_unauthorized(update):
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        facts = await fact_store.get_by_category(update.effective_user.id, "project")
        if not facts:
            await update.message.reply_text("No project set yet.")
            return
        lines = []
        for f in facts:
            path = f["content"]
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
                except Exception:
                    lines.append(f"• {path}")
            else:
                lines.append(f"• {path} _(not found)_")
        await update.message.reply_text(
            "Tracked projects:\n" + "\n".join(lines),
            parse_mode="Markdown",
        )

    async def scan_downloads_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/scan-downloads — rich report: type classification, ages, sizes."""
        if await reject_unauthorized(update):
            return
        downloads = Path.home() / "Downloads"
        if not downloads.exists():
            await update.message.reply_text("Downloads folder not found.")
            return
        try:
            files = [f for f in downloads.iterdir() if f.is_file()]
        except Exception as e:
            await update.message.reply_text(f"❌ Could not scan Downloads: {e}")
            return
        if not files:
            await update.message.reply_text("✅ Downloads folder is empty.")
            return

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

        lines = [f"📦 *Downloads Scan* — {len(files)} files ({_fmt_bytes(total_bytes)} total)\n"]

        lines.append("*Type breakdown:*")
        for label, (icon, count, nbytes) in sorted(type_counts.items(), key=lambda x: -x[1][2]):
            lines.append(f"  {icon} {label}: {count} file(s), {_fmt_bytes(nbytes)}")

        lines.append("\n*Age breakdown:*")
        for bucket, count in age_buckets.items():
            if count:
                suffix = " — consider cleanup" if "Old" in bucket else ""
                lines.append(f"  • {bucket}: {count} file(s){suffix}")

        oldest_sorted = sorted(oldest, key=lambda x: x[0])[:8]
        if oldest_sorted:
            lines.append("\n*Oldest files:*")
            for mtime, name, nbytes in oldest_sorted:
                age_days = int((now - mtime) / 86400)
                lines.append(f"  • {name} ({age_days}d old, {_fmt_bytes(nbytes)})")

        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def organize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/organize <path> — Claude-powered directory organisation suggestions."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /organize <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        p = Path(sanitized)
        if not p.is_dir():
            await update.message.reply_text("❌ Not a directory.")
            return
        try:
            entries = sorted([f.name for f in p.iterdir()])
        except Exception as e:
            await update.message.reply_text(f"❌ Could not list directory: {e}")
            return
        if not entries:
            await update.message.reply_text("Directory is empty.")
            return
        if claude_client is None:
            await update.message.reply_text("Claude not available for suggestions.")
            return
        await update.message.reply_text(
            f"🤔 Analysing {len(entries)} items in `{p.name}`…",
            parse_mode="Markdown",
        )
        listing = "\n".join(entries[:50])
        try:
            suggestions = await claude_client.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Here is the contents of directory '{sanitized}':\n\n{listing}\n\n"
                        "Suggest how to organise these files. "
                        "Recommend folder names and which files should go where. "
                        "Be specific and actionable."
                    ),
                }],
                system="You are a helpful file organisation assistant. Be concise and practical.",
                max_tokens=1024,
            )
            if len(suggestions) > 4000:
                suggestions = suggestions[:4000] + "…"
            await update.message.reply_text(
                f"📁 *Organisation suggestions for {p.name}:*\n\n{suggestions}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Could not generate suggestions: {e}")

    async def clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/clean <path> — Claude suggests DELETE/ARCHIVE/KEEP per file."""
        if await reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /clean <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, settings.allowed_base_dirs)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        p = Path(sanitized)
        if not p.is_dir():
            await update.message.reply_text("❌ Not a directory.")
            return
        try:
            files = sorted([f for f in p.iterdir() if f.is_file()], key=lambda x: x.stat().st_mtime)
        except Exception as e:
            await update.message.reply_text(f"❌ Could not list directory: {e}")
            return
        if not files:
            await update.message.reply_text("No files in directory.")
            return
        if claude_client is None:
            await update.message.reply_text("Claude not available for suggestions.")
            return
        await update.message.reply_text(
            f"🧹 Analysing {len(files)} files in `{p.name}`…",
            parse_mode="Markdown",
        )
        now = time.time()
        file_lines = []
        for f in files[:30]:
            stat = f.stat()
            age_days = int((now - stat.st_mtime) / 86400)
            size_kb = stat.st_size // 1024
            file_lines.append(f"• {f.name} ({size_kb}KB, {age_days}d old)")
        listing = "\n".join(file_lines)
        try:
            suggestions = await claude_client.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Review these files from '{sanitized}' and suggest DELETE, ARCHIVE, or KEEP for each:\n\n{listing}\n\n"
                        "Format your response as:\n"
                        "• filename.ext — KEEP/ARCHIVE/DELETE — brief reason"
                    ),
                }],
                system="You are a helpful file cleanup assistant. Be decisive and practical.",
                max_tokens=1024,
            )
            if len(suggestions) > 4000:
                suggestions = suggestions[:4000] + "…"
            await update.message.reply_text(
                f"🗑 *Cleanup suggestions for {p.name}:*\n\n{suggestions}",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Could not generate suggestions: {e}")

    return {
        "read": read_command,
        "write": write_command,
        "ls": ls_command,
        "find": find_command,
        "set_project": set_project_command,
        "project_status": project_status_command,
        "scan_downloads": scan_downloads_command,
        "organize": organize_command,
        "clean": clean_command,
    }
