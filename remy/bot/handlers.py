"""
Telegram command and message handlers.
All handlers acquire the per-user session lock before processing.

Two processing paths for text input:
  - Tool-aware path (preferred): uses ClaudeClient.stream_with_tools() for
    native Anthropic function calling. Claude autonomously decides when to
    invoke get_logs, get_goals, get_facts, run_board, or check_status.
  - Router fallback: used when tool_registry is not available.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from ..agents.background import BackgroundTaskRunner
from ..ai.claude_client import TextChunk, ToolResultChunk, ToolStatusChunk, ToolTurnComplete
from ..ai.input_validator import (
    RateLimiter,
    validate_command_input,
    validate_message_input,
    sanitize_memory_injection,
    sanitize_file_path,
)
from ..ai.router import ModelRouter
from ..bot.session import SessionManager
from ..bot.streaming import stream_to_telegram
from ..config import settings
from ..diagnostics import get_error_summary, get_recent_logs
from ..exceptions import ServiceUnavailableError
from ..memory.conversations import ConversationStore
from ..memory.facts import FactExtractor, FactStore, extract_and_store_facts
from ..memory.goals import GoalExtractor, GoalStore, extract_and_store_goals
from ..memory.injector import MemoryInjector
from ..models import ConversationTurn

# Avoid circular imports — these are only used for type hints here
if TYPE_CHECKING:
    from ..agents.orchestrator import BoardOrchestrator
    from ..scheduler.proactive import ProactiveScheduler

logger = logging.getLogger(__name__)

# Sentinel prefix used to serialise multi-block tool turns into JSONL conversation store
_TOOL_TURN_PREFIX = "__TOOL_TURN__:"

# Rate limiter: max 10 messages per minute per user
_rate_limiter = RateLimiter(max_messages_per_minute=10)

# Track task start times for 2-hour timeout enforcement
_task_start_times: dict[int, float] = {}
TASK_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 hours

# Filesystem access controls
_ALLOWED_BASE_DIRS = [
    str(Path.home() / "Projects"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Downloads"),
]

# Pending two-step write state: user_id -> sanitized path
_pending_writes: dict[int, str] = {}

# Pending archive confirmation: user_id -> list of Gmail message IDs
_pending_archive: dict[int, list[str]] = {}


def _build_message_from_turn(turn: ConversationTurn) -> dict:
    """
    Convert a ConversationTurn back into an Anthropic messages dict.
    Tool turns are stored as JSON under a sentinel prefix; regular turns
    are plain text.
    """
    if turn.content.startswith(_TOOL_TURN_PREFIX):
        try:
            blocks = json.loads(turn.content[len(_TOOL_TURN_PREFIX):])
            return {"role": turn.role, "content": blocks}
        except (json.JSONDecodeError, ValueError):
            pass
    return {"role": turn.role, "content": turn.content}


# Rough character budget for conversation history passed to Claude.
# Each tool-result turn from a Gmail search can be very large; keeping this
# low prevents TPM rate-limit errors (30k input tokens/min limit).
# Estimate: 4 chars ≈ 1 token → 60k chars ≈ 15k tokens for history.
_HISTORY_CHAR_BUDGET = 60_000

# Funny "working" messages for Telegram
_WORKING_MESSAGES = [
    "Reticulating splines…",
    "Homologating girdles…",
    "Initializing neural pathways…",
    "Consulting the archives…",
    "Synthesizing creative juices…",
    "Parsing the universe…",
    "Herding digital cats…",
    "Buffing the bits…",
    "Aligning the planets…",
    "Calculating the meaning of life…",
    "Polishing the protocols…",
    "Twiddling virtual thumbs…",
    "Brewing digital coffee…",
    "Charging flux capacitors…",
    "Optimizing the optimism…",
    "Rerouting power to thinking…",
]

def _get_working_msg() -> str:
    import random
    return random.choice(_WORKING_MESSAGES)


class MessageRotator:
    """
    Background task that rotates working messages on a Telegram message
    at random intervals until stopped.
    """
    def __init__(self, message: any, user_id: int):
        self._message = message
        self._user_id = user_id
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def _rotate_loop(self):
        import random
        last_msg = ""
        while not self._stop_event.is_set():
            # Get a new random message different from the last one
            pool = [m for m in _WORKING_MESSAGES if m != last_msg]
            msg = random.choice(pool)
            last_msg = msg
            
            try:
                await self._message.edit_text(msg)
            except Exception:
                # Ignore edit errors (rate limits, message deleted, etc)
                pass
            
            # Wait for random interval 0.5s - 2.5s
            wait_time = random.uniform(0.5, 2.5)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_time)
            except asyncio.TimeoutError:
                continue

    def start(self):
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._rotate_loop())

    async def stop(self):
        if self._task:
            self._stop_event.set()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


def _trim_messages_to_budget(messages: list[dict]) -> list[dict]:
    """
    Drop the oldest message pairs from history if the serialised size exceeds
    _HISTORY_CHAR_BUDGET.  Always preserves at least the last 4 messages so
    that the immediate prior exchange stays intact.
    """
    while len(messages) > 4:
        serialised = json.dumps(messages, ensure_ascii=False)
        if len(serialised) <= _HISTORY_CHAR_BUDGET:
            break
        # Drop the first two messages (one user + one assistant pair)
        messages = messages[2:]
    return messages


def make_handlers(
    session_manager: SessionManager,
    router: ModelRouter,
    conv_store: ConversationStore,
    claude_client=None,  # injected for /compact summary and /board
    fact_extractor: FactExtractor | None = None,
    fact_store: FactStore | None = None,
    goal_extractor: GoalExtractor | None = None,
    goal_store: GoalStore | None = None,
    memory_injector: MemoryInjector | None = None,
    voice_transcriber=None,
    proactive_scheduler: "ProactiveScheduler | None" = None,
    board_orchestrator: "BoardOrchestrator | None" = None,
    db=None,  # DatabaseManager — used to upsert user on first message
    tool_registry=None,  # ToolRegistry — enables native Anthropic tool use
    google_calendar=None,  # remy.google.calendar.CalendarClient | None
    google_gmail=None,     # remy.google.gmail.GmailClient | None
    google_docs=None,      # remy.google.docs.DocsClient | None
    google_contacts=None,  # remy.google.contacts.ContactsClient | None
    automation_store=None,  # remy.memory.automations.AutomationStore | None
    scheduler_ref: dict | None = None,  # mutable {"proactive_scheduler": ...} for late-binding
    conversation_analyzer=None,  # remy.analytics.analyzer.ConversationAnalyzer | None
):
    """
    Factory that returns handler functions bound to shared dependencies.
    Register the returned handlers with the Telegram Application.
    """

    def _is_allowed(user_id: int) -> bool:
        if not settings.telegram_allowed_users:
            return True
        return user_id in settings.telegram_allowed_users

    async def _reject_unauthorized(update: Update) -> bool:
        if not _is_allowed(update.effective_user.id):
            await update.message.reply_text(
                "You are not authorised to use this bot."
            )
            return True
        return False

    # ------------------------------------------------------------------ #
    # Commands                                                             #
    # ------------------------------------------------------------------ #

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _reject_unauthorized(update):
            return
        await update.message.reply_text(
            "Remy online.\n\n"
            "Commands:\n"
            "  /help      — show this list\n"
            "  /cancel    — stop current task\n"
            "  /compact   — summarise and compress conversation\n"
            "  /delete_conversation — delete conversation history for privacy\n"
            "  /status    — check backend status\n"
            "  /goals     — list your active goals\n"
            "  /read <path> — read a text file (Projects/Documents/Downloads)\n"
            "  /write <path> — write text to a file (you'll be prompted for content)\n"
            "  /ls <dir> — list files in a directory\n"
            "  /find <pattern> — search filenames under allowed bases\n"
            "  /set_project <path> — mark current project (stored in memory)\n"
            "  /project_status — show currently tracked project(s)\n"
            "  /scan_downloads — check ~/Downloads for clutter\n"
            "  /organize <path> — Claude suggests how to organise a directory\n"
            "  /clean <path>    — Claude suggests DELETE/ARCHIVE/KEEP per file\n"
            "  /logs      — diagnostics summary (errors + tail)\n"
            "  /logs tail [N] — last N raw log lines (default 30)\n"
            "  /logs errors   — errors and warnings only\n"
            "  /calendar [days] — upcoming calendar events (default 7 days)\n"
            "  /calendar-today  — today's schedule at a glance\n"
            "  /schedule <title> <YYYY-MM-DD> <HH:MM> — create a calendar event\n"
            "  /gmail-unread [N] — show N unread emails (default 5)\n"
            "  /gmail-unread-summary — total count + top senders\n"
            "  /gmail-classify — find promotional/newsletter emails\n"
            "  /gmail-search <query> — search all Gmail (supports from:, subject:, label:, etc.)\n"
            "  /gmail-read <id> — read the full body of an email by ID\n"
            "  /gmail-labels — list all Gmail labels and their IDs\n"
            "  /gdoc <url-or-id> — read a Google Doc\n"
            "  /gdoc-append <url-or-id> <text> — append text to a Google Doc\n"
            "  /contacts [query] — list or search Google Contacts\n"
            "  /contacts-birthday [days] — upcoming birthdays (default 14 days)\n"
            "  /contacts-details <name> — full contact card\n"
            "  /contacts-note <name> <note> — add/update a note on a contact\n"
            "  /contacts-prune — find contacts missing email + phone\n"
            "  /search <query>  — DuckDuckGo web search\n"
            "  /research <topic> — search + Claude synthesis\n"
            "  /save-url <url> [note] — save a bookmark\n"
            "  /bookmarks [filter] — list saved bookmarks\n"
            "  /grocery-list [add/done/clear] — grocery list management\n"
            "  /price-check <item> — search for current prices\n"
            "  /briefing  — get your morning briefing now\n"
            "  /setmychat — set this chat for proactive messages\n"
            "  /board <topic> — convene the Board of Directors\n"
            "  /schedule_daily [HH:MM] <task>        — remind me daily\n"
            "  /schedule_weekly [day] [HH:MM] <task> — remind me weekly\n"
            "  /list_automations — show scheduled reminders\n"
            "  /unschedule <id>  — remove a scheduled reminder\n"
            "  /breakdown <task> — break a task into actionable steps\n"
            "  /stats [period]   — usage stats (7d, 30d, 90d, all)\n"
            "  /goal-status      — goal tracking dashboard\n"
            "  /retrospective    — generate monthly retrospective\n\n"
            "Send a voice message to transcribe and process it.\n"
            "Just send me a message to get started."
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await start_command(update, context)

    async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _reject_unauthorized(update):
            return
        user_id = update.effective_user.id
        session_manager.request_cancel(user_id)
        # Clear task timer
        _task_start_times.pop(user_id, None)
        await update.message.reply_text("Stopping current task…")

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _reject_unauthorized(update):
            return
        
        # Use the central status check from ToolRegistry
        status_text = await tool_registry.dispatch("check_status", {}, update.effective_user.id)
        await update.message.reply_text(status_text)

    async def compact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _reject_unauthorized(update):
            return
        user_id = update.effective_user.id
        session_key = SessionManager.get_session_key(user_id)
        turns = await conv_store.get_recent_turns(user_id, session_key, limit=50)

        if not turns:
            await update.message.reply_text("No conversation to compact.")
            return

        if claude_client is None:
            await update.message.reply_text("Compact unavailable — no Claude client.")
            return

        await update.message.reply_text("Summarising conversation…")
        transcript = "\n".join(
            f"{t.role.upper()}: {t.content[:500]}" for t in turns
        )
        summary = await claude_client.complete(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Summarise this conversation in 3-5 bullet points, "
                        f"preserving key facts, decisions, and context.\n\n{transcript}"
                    ),
                }
            ],
            system="You are a summarisation assistant. Be concise and factual.",
            max_tokens=512,
        )
        await conv_store.compact(user_id, session_key, summary)
        await update.message.reply_text(f"Conversation compacted.\n\n{summary}")

    async def setmychat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _reject_unauthorized(update):
            return
        chat_id = str(update.effective_chat.id)
        path = settings.primary_chat_file
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            with open(path, "w") as f:
                f.write(chat_id)
            await update.message.reply_text(
                f"This chat is now set for proactive messages. (ID: {chat_id})"
            )
        except OSError as e:
            await update.message.reply_text(f"Could not save: {e}")

    async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger the morning briefing right now."""
        if await _reject_unauthorized(update):
            return
        if proactive_scheduler is None:
            await update.message.reply_text("Proactive scheduler not running.")
            return
        await update.message.reply_text("Sending briefing…")
        await proactive_scheduler.send_morning_briefing_now()

    async def goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List your currently active goals."""
        if await _reject_unauthorized(update):
            return
        if goal_store is None:
            await update.message.reply_text("Memory not available.")
            return
        user_id = update.effective_user.id
        goals = await goal_store.get_active(user_id, limit=15)
        if not goals:
            await update.message.reply_text(
                "You have no active goals yet. Tell me what you're working on!"
            )
            return
        lines = [f"• *{g['title']}*" + (f" — {g['description']}" if g.get("description") else "")
                 for g in goals]
        await update.message.reply_text(
            f"🎯 *Active goals* ({len(goals)}):\n\n" + "\n".join(lines),
            parse_mode="Markdown",
        )

    async def delete_conversation_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete conversation history for privacy."""
        if await _reject_unauthorized(update):
            return
        user_id = update.effective_user.id
        session_key = SessionManager.get_session_key(user_id)
        try:
            await conv_store.delete_session(user_id, session_key)
            # Clear task timer for this user
            _task_start_times.pop(user_id, None)
            await update.message.reply_text(
                "Conversation deleted. Starting fresh — new session begins now."
            )
        except Exception as e:
            logger.error("Failed to delete conversation for user %d: %s", user_id, e)
            await update.message.reply_text(f"Could not delete conversation: {e}")

    # ----------------- file / project commands -----------------------

    async def read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/read <path> — return contents of a text file in allowed dirs. Files >50KB are summarised."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /read <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, _ALLOWED_BASE_DIRS)
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
            # Read first 20 000 chars for summarisation
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
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /write <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, _ALLOWED_BASE_DIRS)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        _pending_writes[update.effective_user.id] = sanitized
        await update.message.reply_text(
            f"Send me the text you want to write to {sanitized}."
        )

    async def ls_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/ls <dir> — list files in a directory under allowed bases."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /ls <directory>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, _ALLOWED_BASE_DIRS)
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
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /find <glob-pattern>")
            return
        pattern = context.args[0]
        import glob
        raw_results = []
        for base in _ALLOWED_BASE_DIRS:
            raw_results.extend(glob.glob(os.path.join(base, "**", pattern), recursive=True))
        # Validate every result is within an allowed base (guards against crafted patterns)
        results = []
        for r in raw_results:
            safe, err = sanitize_file_path(r, _ALLOWED_BASE_DIRS)
            if safe and not err:
                results.append(safe)
        results = results[:20]
        if not results:
            await update.message.reply_text("No matching files found.")
        else:
            await update.message.reply_text("\n".join(results))

    async def set_project_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/set-project <path> — remember a project location."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /set_project <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, _ALLOWED_BASE_DIRS)
        if err or sanitized is None:
            await update.message.reply_text(f"❌ {err}")
            return
        # record as a fact
        from ..models import Fact
        fact = Fact(category="project", content=sanitized)
        if fact_store is not None:
            await fact_store.upsert(update.effective_user.id, [fact])
        await update.message.reply_text(f"Project set: {sanitized}")

    async def project_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/project-status — list remembered project paths with file count and last modified."""
        if await _reject_unauthorized(update):
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        facts = await fact_store.get_by_category(update.effective_user.id, "project")
        if not facts:
            await update.message.reply_text("No project set yet.")
            return
        from datetime import datetime as _dt
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
        if await _reject_unauthorized(update):
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

        # Extension → (icon, label)
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

        # label -> (icon, count, bytes)
        type_counts: dict[str, tuple[str, int, int]] = {}
        age_buckets = {"Today (<1d)": 0, "This week (<7d)": 0, "This month (<30d)": 0, "Old (>30d)": 0}
        # (mtime, name, size_bytes) — for oldest-files list
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
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /organize <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, _ALLOWED_BASE_DIRS)
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
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /clean <path>")
            return
        path_arg = " ".join(context.args)
        sanitized, err = sanitize_file_path(path_arg, _ALLOWED_BASE_DIRS)
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
        for f in files[:30]:  # oldest first, cap at 30
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

    # ------------------------------------------------------------------ #
    # Google Calendar commands                                             #
    # ------------------------------------------------------------------ #

    def _google_not_configured(service: str) -> str:
        return (
            f"❌ Google {service} not configured.\n"
            "Run `python scripts/setup_google_auth.py` to authenticate."
        )

    async def calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/calendar [days=7] — list upcoming calendar events."""
        if await _reject_unauthorized(update):
            return
        if google_calendar is None:
            await update.message.reply_text(_google_not_configured("Calendar"))
            return
        try:
            days = int(context.args[0]) if context.args else 7
            days = max(1, min(days, 30))
        except (ValueError, IndexError):
            days = 7
        await update.message.reply_text("📅 Fetching calendar…")
        try:
            events = await google_calendar.list_events(days=days)
        except Exception as e:
            await update.message.reply_text(f"❌ Calendar error: {e}")
            return
        if not events:
            await update.message.reply_text(f"📅 No events in the next {days} day(s).")
            return
        lines = [f"📅 *Next {days} day(s):*"]
        prev_date = None
        for ev in events:
            start = ev.get("start", {})
            dt_str = start.get("dateTime", start.get("date", ""))
            date_part = dt_str[:10] if dt_str else ""
            if date_part != prev_date:
                lines.append(f"\n_{date_part}_")
                prev_date = date_part
            lines.append(google_calendar.format_event(ev))
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def calendar_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/calendar-today — today's events at a glance."""
        context.args = ["1"]
        await calendar_command(update, context)

    async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/schedule <title> <YYYY-MM-DD> <HH:MM> — create a calendar event (1-hour block)."""
        if await _reject_unauthorized(update):
            return
        if google_calendar is None:
            await update.message.reply_text(_google_not_configured("Calendar"))
            return
        if not context.args or len(context.args) < 3:
            await update.message.reply_text(
                "Usage: /schedule <title> <YYYY-MM-DD> <HH:MM>\n"
                "Example: /schedule Team standup 2026-03-01 09:00"
            )
            return
        date_str = context.args[-2]
        time_str = context.args[-1]
        title = " ".join(context.args[:-2])
        if not title:
            await update.message.reply_text("❌ Title cannot be empty.")
            return
        try:
            event = await google_calendar.create_event(title, date_str, time_str)
            link = event.get("htmlLink", "")
            link_suffix = f"\n[Open in Google Calendar]({link})" if link else ""
            await update.message.reply_text(
                f"✅ *Event created:* {title}\n"
                f"📅 {date_str} at {time_str} (1 hour){link_suffix}",
                parse_mode="Markdown",
            )
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not create event: {e}")

    # ------------------------------------------------------------------ #
    # Gmail commands                                                       #
    # ------------------------------------------------------------------ #

    async def gmail_unread_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-unread [limit=5] — show and summarise unread inbox emails."""
        if await _reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(_google_not_configured("Gmail"))
            return
        try:
            limit = int(context.args[0]) if context.args else 5
            limit = max(1, min(limit, 20))
        except (ValueError, IndexError):
            limit = 5
        await update.message.reply_text("📬 Fetching unread emails…")
        try:
            emails = await google_gmail.get_unread(limit=limit)
        except Exception as e:
            await update.message.reply_text(f"❌ Gmail error: {e}")
            return
        if not emails:
            await update.message.reply_text("📬 No unread emails in inbox.")
            return
        lines = [f"📬 *Unread emails ({len(emails)} shown):*\n"]
        for i, e in enumerate(emails, 1):
            subject = e["subject"][:80]
            sender = e["from_addr"][:60]
            snippet = e["snippet"][:120].replace("\n", " ")
            lines.append(f"*{i}.* {subject}\n   From: {sender}\n   _{snippet}_\n")
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def gmail_unread_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-unread-summary — total unread count and top senders."""
        if await _reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(_google_not_configured("Gmail"))
            return
        await update.message.reply_text("📬 Checking inbox…")
        try:
            summary = await google_gmail.get_unread_summary()
        except Exception as e:
            await update.message.reply_text(f"❌ Gmail error: {e}")
            return
        count = summary["count"]
        if count == 0:
            await update.message.reply_text("📬 Inbox is clear — no unread emails.")
            return
        senders = summary["senders"]
        sender_lines = "\n".join(f"  • {s}" for s in senders[:8])
        await update.message.reply_text(
            f"📬 *{count} unread email(s)*\n\nTop senders:\n{sender_lines}",
            parse_mode="Markdown",
        )

    async def gmail_classify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-classify — identify promotional/newsletter emails and offer to archive."""
        if await _reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(_google_not_configured("Gmail"))
            return
        await update.message.reply_text("🔍 Scanning inbox for promotional emails…")
        try:
            promos = await google_gmail.classify_promotional(limit=30)
        except Exception as e:
            await update.message.reply_text(f"❌ Gmail error: {e}")
            return
        if not promos:
            await update.message.reply_text("✅ No promotional emails detected.")
            return
        user_id = update.effective_user.id
        _pending_archive[user_id] = [e["id"] for e in promos]
        lines = [f"🗑 *{len(promos)} promotional email(s) found:*\n"]
        for e in promos[:10]:
            lines.append(f"• {e['subject'][:80]}\n  _From: {e['from_addr'][:60]}_")
        if len(promos) > 10:
            lines.append(f"…and {len(promos) - 10} more")
        lines.append(
            f"\nReply *yes* to archive all {len(promos)} emails, or anything else to cancel."
        )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def gmail_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-search <query> — search all Gmail with Gmail query syntax."""
        if await _reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(_google_not_configured("Gmail"))
            return
        if not context.args:
            await update.message.reply_text(
                "Usage: `/gmail-search <query>`\n"
                "Examples:\n"
                "  `/gmail-search from:kathryn hockey`\n"
                "  `/gmail-search subject:invoice after:2025/1/1`\n"
                "  `/gmail-search label:ALL_MAIL is:unread`",
                parse_mode="Markdown",
            )
            return
        query = " ".join(context.args)
        await update.message.reply_text(f"🔍 Searching for `{query}`…", parse_mode="Markdown")
        try:
            emails = await google_gmail.search(query, max_results=10)
        except Exception as e:
            await update.message.reply_text(f"❌ Gmail error: {e}")
            return
        if not emails:
            await update.message.reply_text(f"No emails found for: {query}")
            return
        lines = [f"📬 *{len(emails)} result(s) for* `{query}`:\n"]
        for e in emails:
            mid = e["id"]
            lines.append(
                f"• `{mid}`\n"
                f"  *{e['subject'][:80]}*\n"
                f"  From: {e['from_addr'][:60]}\n"
                f"  {e['date'][:30]}"
            )
        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

    async def gmail_read_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-read <message-id> — read the full body of a specific email."""
        if await _reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(_google_not_configured("Gmail"))
            return
        if not context.args:
            await update.message.reply_text("Usage: `/gmail-read <message-id>`", parse_mode="Markdown")
            return
        message_id = context.args[0]
        await update.message.reply_text("📖 Fetching email…")
        try:
            from ..ai.input_validator import sanitize_memory_injection
            m = await google_gmail.get_message(message_id, include_body=True)
            subj   = sanitize_memory_injection(m.get("subject", "(no subject)"))
            sender = sanitize_memory_injection(m.get("from_addr", ""))
            date   = m.get("date", "")
            body   = sanitize_memory_injection(m.get("body") or m.get("snippet", ""))
            text = (
                f"*{subj}*\n"
                f"From: {sender}\n"
                f"Date: {date}\n\n"
                f"{body}"
            )
            if len(text) > 4000:
                text = text[:3990] + "\n\n…_(truncated)_"
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Gmail error: {e}")

    async def gmail_labels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gmail-labels — list all Gmail labels and their IDs."""
        if await _reject_unauthorized(update):
            return
        if google_gmail is None:
            await update.message.reply_text(_google_not_configured("Gmail"))
            return
        try:
            labels = await google_gmail.list_labels()
            user_labels = [l for l in labels if l["type"] != "system"]
            sys_labels  = [l for l in labels if l["type"] == "system"]
            lines = ["*Gmail Labels*\n"]
            if user_labels:
                lines.append("*Custom:*")
                for l in sorted(user_labels, key=lambda x: x["name"]):
                    lines.append(f"  `{l['id']}` — {l['name']}")
            lines.append("\n*System:*")
            for l in sorted(sys_labels, key=lambda x: x["name"]):
                lines.append(f"  `{l['id']}` — {l['name']}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Gmail error: {e}")

    # ------------------------------------------------------------------ #
    # Google Docs commands                                                 #
    # ------------------------------------------------------------------ #

    async def gdoc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gdoc <url-or-id> — read a Google Doc (large docs are summarised)."""
        if await _reject_unauthorized(update):
            return
        if google_docs is None:
            await update.message.reply_text(_google_not_configured("Docs"))
            return
        if not context.args:
            await update.message.reply_text("Usage: /gdoc <google-doc-url-or-id>")
            return
        id_or_url = context.args[0]
        await update.message.reply_text("📄 Fetching document…")
        try:
            title, text = await google_docs.read_document(id_or_url)
        except Exception as e:
            await update.message.reply_text(f"❌ Could not fetch doc: {e}")
            return
        _SIZE_50KB = 50 * 1024
        if len(text.encode()) > _SIZE_50KB and claude_client is not None:
            await update.message.reply_text(
                f"📄 *{title}* is large. Summarising…", parse_mode="Markdown"
            )
            try:
                summary = await claude_client.complete(
                    messages=[{"role": "user", "content": f"Summarise this document:\n\n{text[:20000]}"}],
                    system="You are a document summarisation assistant. Be concise and factual.",
                    max_tokens=512,
                )
                await update.message.reply_text(
                    f"📄 *Summary of {title}:*\n\n{summary}", parse_mode="Markdown"
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Could not summarise: {e}")
            return
        if len(text) > 8000:
            text = text[:8000] + "\n…[truncated]"
        await update.message.reply_text(
            f"📄 *{title}*\n\n```\n{text}\n```",
            parse_mode="Markdown",
        )

    async def gdoc_append_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/gdoc-append <url-or-id> <text> — append text to a Google Doc."""
        if await _reject_unauthorized(update):
            return
        if google_docs is None:
            await update.message.reply_text(_google_not_configured("Docs"))
            return
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /gdoc-append <google-doc-url-or-id> <text to append>"
            )
            return
        id_or_url = context.args[0]
        text_to_append = " ".join(context.args[1:])
        try:
            await google_docs.append_text(id_or_url, text_to_append)
            await update.message.reply_text("✅ Text appended to document.")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not append to doc: {e}")

    # ------------------------------------------------------------------ #
    # Google Contacts (People API)                                        #
    # ------------------------------------------------------------------ #

    async def contacts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts [query] — list all contacts or search by name/email."""
        if await _reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(_google_not_configured("Contacts"))
            return
        query = " ".join(context.args).strip() if context.args else ""
        if query:
            await update.message.reply_text(f"🔍 Searching contacts for _{query}_…", parse_mode="Markdown")
            try:
                people = await google_contacts.search_contacts(query, max_results=10)
            except Exception as e:
                await update.message.reply_text(f"❌ Contacts search failed: {e}")
                return
            if not people:
                await update.message.reply_text(f"No contacts matching _{query}_.", parse_mode="Markdown")
                return
        else:
            await update.message.reply_text("📋 Fetching contacts…")
            try:
                people = await google_contacts.list_contacts(max_results=50)
            except Exception as e:
                await update.message.reply_text(f"❌ Could not fetch contacts: {e}")
                return
            if not people:
                await update.message.reply_text("No contacts found.")
                return

        from ..google.contacts import format_contact
        lines = [f"👥 *{len(people)} contact(s):*\n"]
        for p in people[:20]:
            lines.append(format_contact(p))
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def contacts_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-birthday [days=14] — upcoming birthdays."""
        if await _reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(_google_not_configured("Contacts"))
            return
        try:
            days = int(context.args[0]) if context.args else 14
            days = max(1, min(days, 90))
        except (ValueError, IndexError):
            days = 14
        await update.message.reply_text(f"🎂 Checking birthdays in the next {days} days…")
        try:
            upcoming = await google_contacts.get_upcoming_birthdays(days=days)
        except Exception as e:
            await update.message.reply_text(f"❌ Could not fetch birthdays: {e}")
            return
        if not upcoming:
            await update.message.reply_text(f"🎂 No birthdays in the next {days} days.")
            return
        from ..google.contacts import _extract_name
        lines = [f"🎂 *Upcoming birthdays (next {days} days):*\n"]
        for bday_date, person in upcoming:
            name = _extract_name(person) or "(unknown)"
            yr = f" {bday_date.year}" if bday_date.year != 1900 else ""
            lines.append(f"• *{name}* — {bday_date.strftime('%d %b')}{yr}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def contacts_details_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-details <name> — full details for a contact."""
        if await _reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(_google_not_configured("Contacts"))
            return
        if not context.args:
            await update.message.reply_text("Usage: /contacts-details <name>")
            return
        query = " ".join(context.args)
        try:
            people = await google_contacts.search_contacts(query, max_results=5)
        except Exception as e:
            await update.message.reply_text(f"❌ Search failed: {e}")
            return
        if not people:
            await update.message.reply_text(f"No contact found matching _{query}_.", parse_mode="Markdown")
            return
        from ..google.contacts import format_contact, _extract_name
        # Fetch full details for the top match
        top = people[0]
        resource_name = top.get("resourceName", "")
        try:
            if resource_name:
                top = await google_contacts.get_contact(resource_name)
        except Exception:
            pass  # fall back to search result
        lines = [f"👤 *Contact details:*\n", format_contact(top, verbose=True)]
        if len(people) > 1:
            others = [_extract_name(p) or "?" for p in people[1:]]
            lines.append(f"\n_Also matched: {', '.join(others)}_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def contacts_note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-note <name> <note> — add/update a note on a contact."""
        if await _reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(_google_not_configured("Contacts"))
            return
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Usage: /contacts-note <name> <note text>")
            return
        # Heuristic: first word(s) that match a contact name, rest is the note
        # We search with the first arg, then user provides note as remaining args
        name_query = context.args[0]
        note_text = " ".join(context.args[1:])
        try:
            people = await google_contacts.search_contacts(name_query, max_results=3)
        except Exception as e:
            await update.message.reply_text(f"❌ Search failed: {e}")
            return
        if not people:
            await update.message.reply_text(
                f"No contact matching _{name_query}_.\n"
                "Usage: /contacts-note <first-name> <note text>",
                parse_mode="Markdown",
            )
            return
        from ..google.contacts import _extract_name
        person = people[0]
        resource_name = person.get("resourceName", "")
        name = _extract_name(person) or name_query
        try:
            await google_contacts.update_note(resource_name, note_text)
            await update.message.reply_text(
                f"✅ Note updated for *{name}*:\n_{note_text}_",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Could not update note: {e}")

    async def contacts_prune_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/contacts-prune — list contacts with no email and no phone (candidates for deletion)."""
        if await _reject_unauthorized(update):
            return
        if google_contacts is None:
            await update.message.reply_text(_google_not_configured("Contacts"))
            return
        await update.message.reply_text("🔍 Scanning for sparse contacts…")
        try:
            sparse = await google_contacts.get_sparse_contacts(max_results=300)
        except Exception as e:
            await update.message.reply_text(f"❌ Could not scan contacts: {e}")
            return
        if not sparse:
            await update.message.reply_text("✅ All contacts have at least an email or phone number.")
            return
        from ..google.contacts import _extract_name
        lines = [f"🗑 *{len(sparse)} contact(s) with no email or phone:*\n"]
        for p in sparse[:30]:
            name = _extract_name(p) or "(no name)"
            lines.append(f"• {name}")
        if len(sparse) > 30:
            lines.append(f"…and {len(sparse) - 30} more")
        lines.append("\n_Use /contacts-details <name> to review, or delete in Google Contacts._")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ------------------------------------------------------------------ #
    # Phase 4: Web search, bookmarks, grocery list                        #
    # ------------------------------------------------------------------ #

    async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/search <query> — DuckDuckGo web search, returns top results."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /search <query>")
            return
        from ..web.search import web_search, format_results
        query = " ".join(context.args)
        await update.message.reply_text(f"🔍 Searching for _{query}_…", parse_mode="Markdown")
        results = await web_search(query, max_results=5)
        if not results:
            await update.message.reply_text(
                "❌ Search unavailable right now. "
                "Make sure `duckduckgo-search` is installed, or try again later."
            )
            return
        msg = f"🔍 *Results for \"{query}\":*\n\n" + format_results(results)
        if len(msg) > 4000:
            msg = msg[:4000] + "…"
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/research <topic> — web search + Claude synthesis of findings."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /research <topic>")
            return
        if claude_client is None:
            await update.message.reply_text("❌ Claude not available for research synthesis.")
            return
        from ..web.search import web_search
        topic = " ".join(context.args)
        await update.message.reply_text(f"📚 Researching _{topic}_…", parse_mode="Markdown")
        results = await web_search(topic, max_results=5)
        if not results:
            await update.message.reply_text(
                "❌ Web search unavailable. Install `duckduckgo-search` or try again later."
            )
            return
        # Build context block for Claude
        snippets = "\n\n".join(
            f"Source {i}: {r.get('title','')}\nURL: {r.get('href','')}\n{r.get('body','')}"
            for i, r in enumerate(results, 1)
        )
        try:
            synthesis = await claude_client.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Research topic: {topic}\n\n"
                        f"Web search results:\n{snippets}\n\n"
                        "Synthesise the key findings into a clear, useful summary. "
                        "Cite source numbers. Be factual and concise."
                    ),
                }],
                system="You are a research assistant. Synthesise web search results accurately.",
                max_tokens=1024,
            )
            msg = f"📚 *Research: {topic}*\n\n{synthesis}"
            if len(msg) > 4000:
                msg = msg[:4000] + "…"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not synthesise results: {e}")

    async def save_url_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/save-url <url> [note] — save a bookmark."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /save-url <url> [optional note]")
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        url = context.args[0]
        note = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        content = f"{url} — {note}" if note else url
        await fact_store.add(update.effective_user.id, "bookmark", content)
        await update.message.reply_text(
            f"🔖 Bookmark saved: {content}", parse_mode="Markdown"
        )

    async def bookmarks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/bookmarks [filter] — list saved bookmarks, optionally filtered."""
        if await _reject_unauthorized(update):
            return
        if fact_store is None:
            await update.message.reply_text("Memory not available.")
            return
        items = await fact_store.get_by_category(update.effective_user.id, "bookmark")
        if not items:
            await update.message.reply_text("🔖 No bookmarks saved yet. Use /save-url <url> to add one.")
            return
        filt = " ".join(context.args).lower() if context.args else ""
        if filt:
            items = [b for b in items if filt in b["content"].lower()]
        if not items:
            await update.message.reply_text(f"🔖 No bookmarks matching '{filt}'.")
            return
        lines = [f"🔖 *Bookmarks{' (filtered)' if filt else ''} — {len(items)} item(s):*\n"]
        for i, b in enumerate(items[:20], 1):
            lines.append(f"{i}. {b['content']}")
        if len(items) > 20:
            lines.append(f"…and {len(items) - 20} more")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def grocery_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /grocery-list              — show current list
        /grocery-list add <items>  — add items (comma-separated or space-separated)
        /grocery-list done <item>  — remove item by name
        /grocery-list clear        — clear the whole list
        """
        if await _reject_unauthorized(update):
            return

        grocery_file = settings.grocery_list_file

        def _read_items() -> list[str]:
            try:
                with open(grocery_file, encoding="utf-8") as f:
                    return [line.strip() for line in f if line.strip()]
            except FileNotFoundError:
                return []

        def _write_items(items: list[str]) -> None:
            Path(grocery_file).parent.mkdir(parents=True, exist_ok=True)
            with open(grocery_file, "w", encoding="utf-8") as f:
                f.write("\n".join(items) + ("\n" if items else ""))

        sub = context.args[0].lower() if context.args else ""

        if sub == "add":
            raw = " ".join(context.args[1:])
            if not raw:
                await update.message.reply_text("Usage: /grocery-list add <items>")
                return
            new_items = [i.strip() for i in raw.split(",") if i.strip()] if "," in raw else [raw.strip()]
            current = await asyncio.to_thread(_read_items)
            await asyncio.to_thread(_write_items, current + new_items)
            added = ", ".join(new_items)
            await update.message.reply_text(f"✅ Added: {added}")

        elif sub == "done":
            item_name = " ".join(context.args[1:]).strip().lower()
            if not item_name:
                await update.message.reply_text("Usage: /grocery-list done <item>")
                return
            current = await asyncio.to_thread(_read_items)
            updated = [i for i in current if i.lower() != item_name]
            if len(updated) == len(current):
                await update.message.reply_text(f"❌ '{item_name}' not found in the list.")
                return
            await asyncio.to_thread(_write_items, updated)
            await update.message.reply_text(f"✅ Removed: {item_name}")

        elif sub == "clear":
            await asyncio.to_thread(_write_items, [])
            await update.message.reply_text("✅ Grocery list cleared.")

        else:
            # Show current list (any unknown subcommand falls through here)
            items = await asyncio.to_thread(_read_items)
            if not items:
                await update.message.reply_text(
                    "🛒 Grocery list is empty.\n"
                    "Use `/grocery-list add milk, eggs, bread` to add items.",
                    parse_mode="Markdown",
                )
                return
            lines = [f"🛒 *Grocery list — {len(items)} item(s):*\n"]
            lines += [f"• {item}" for item in items]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def price_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/price-check <item> — search for current prices and synthesise with Claude."""
        if await _reject_unauthorized(update):
            return
        if not context.args:
            await update.message.reply_text("Usage: /price-check <item>")
            return
        from ..web.search import web_search
        item = " ".join(context.args)
        await update.message.reply_text(f"🏷 Checking prices for _{item}_…", parse_mode="Markdown")
        # Search for the item with price-intent query
        results = await web_search(f"{item} price Australia buy", max_results=5)
        if not results:
            await update.message.reply_text("❌ Web search unavailable right now.")
            return
        if claude_client is None:
            # No Claude — just show raw results
            from ..web.search import format_results
            await update.message.reply_text(
                f"🏷 *Price results for {item}:*\n\n" + format_results(results),
                parse_mode="Markdown",
            )
            return
        snippets = "\n\n".join(
            f"Source {i}: {r.get('title','')}\n{r.get('body','')}"
            for i, r in enumerate(results, 1)
        )
        try:
            analysis = await claude_client.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Item: {item}\n\nSearch results:\n{snippets}\n\n"
                        "Extract and compare the prices mentioned. "
                        "List the best options with their prices and sources. "
                        "Be concise and factual."
                    ),
                }],
                system="You are a shopping assistant. Extract and compare prices from search results.",
                max_tokens=512,
            )
            msg = f"🏷 *Price check: {item}*\n\n{analysis}"
            if len(msg) > 4000:
                msg = msg[:4000] + "…"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not analyse prices: {e}")

    async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /logs          — recent errors and warnings summary
        /logs tail     — last 30 raw log lines
        /logs tail N   — last N raw log lines (max 100)
        /logs errors   — errors only
        """
        if await _reject_unauthorized(update):
            return

        args = context.args or []
        subcommand = args[0].lower() if args else "summary"

        if subcommand == "tail":
            # Parse optional line count
            try:
                n = min(int(args[1]), 100) if len(args) > 1 else 30
            except ValueError:
                n = 30
            raw = get_recent_logs(settings.logs_dir, lines=n)
            # Truncate to fit Telegram's 4096 char limit
            if len(raw) > 3800:
                raw = "…(truncated)\n" + raw[-3800:]
            await update.message.reply_text(
                f"📄 *Last {n} log lines:*\n\n```\n{raw}\n```",
                parse_mode="Markdown",
            )

        elif subcommand == "errors":
            summary = get_error_summary(settings.logs_dir, max_items=10)
            await update.message.reply_text(
                f"🔍 *Error summary:*\n\n{summary}",
                parse_mode="Markdown",
            )

        else:
            # Default: error/warning summary + last 10 lines
            summary = get_error_summary(settings.logs_dir, max_items=5)
            tail = get_recent_logs(settings.logs_dir, lines=10)
            if len(tail) > 1500:
                tail = "…(truncated)\n" + tail[-1500:]
            await update.message.reply_text(
                f"🩺 *Diagnostics*\n\n{summary}\n\n"
                f"*Recent log tail:*\n```\n{tail}\n```\n\n"
                f"_/logs tail — full tail  |  /logs errors — errors only_",
                parse_mode="Markdown",
            )

    async def board_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /board <topic> — convene the Board of Directors on a topic.

        Acknowledges immediately and runs agents in the background, delivering
        the full result as a new message when complete.
        """
        if await _reject_unauthorized(update):
            return

        if board_orchestrator is None:
            await update.message.reply_text(
                "Board of Directors not available — claude_client not configured."
            )
            return

        topic = " ".join(context.args or []).strip()
        if not topic:
            await update.message.reply_text(
                "Usage: /board <topic>\n\n"
                "Example: /board What should I focus on this quarter?"
            )
            return

        user_id = update.effective_user.id

        # Optionally inject user memory so agents can personalise their advice
        user_context = ""
        if memory_injector is not None:
            try:
                full_prompt = await memory_injector.build_system_prompt(
                    user_id, topic, ""
                )
                if "<memory>" in full_prompt:
                    start = full_prompt.index("<memory>")
                    end = full_prompt.index("</memory>") + len("</memory>")
                    user_context = full_prompt[start:end]
            except Exception as exc:
                logger.warning("Board memory injection failed: %s", exc)

        # Acknowledge immediately and release the session lock
        await update.message.reply_text("Started — I'll message you when done 🔄")

        async def _collect_board() -> str:
            chunks = [f"🏛 *Board of Directors: {topic}*\n\n"]
            async for chunk in board_orchestrator.run_board_streaming(topic, user_context):
                chunks.append(chunk)
            return "".join(chunks)

        runner = BackgroundTaskRunner(context.bot, update.message.chat_id)
        asyncio.create_task(runner.run(_collect_board(), label="board analysis"))

    # ------------------------------------------------------------------ #
    # Phase 5: Task automation commands                                     #
    # ------------------------------------------------------------------ #

    def _parse_schedule_args(args: list[str], default_dow: str = "*") -> tuple[str, str]:
        """
        Parse optional [day] [HH:MM] prefix from a /schedule-* command's args.

        Returns (cron_str, label) where label is the remainder of the args joined.

        Accepted prefixes (all optional):
          HH:MM        — time of day (24h), day-of-week stays as default
          day          — day name (mon/tue/…/sun) or number (0-6); no time
          day HH:MM    — both
        """
        remaining = list(args)
        hour = "9"
        minute = "0"
        dow = default_dow

        # Check for leading day-of-week token
        _DOW_MAP = {
            "mon": "1", "tue": "2", "wed": "3", "thu": "4",
            "fri": "5", "sat": "6", "sun": "0",
        }
        if remaining and remaining[0].lower() in _DOW_MAP:
            dow = _DOW_MAP[remaining.pop(0).lower()]

        # Check for leading HH:MM token
        if remaining and ":" in remaining[0]:
            parts = remaining.pop(0).split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hour = parts[0].lstrip("0") or "0"
                minute = parts[1].lstrip("0") or "0"

        label = " ".join(remaining).strip()
        cron = f"{minute} {hour} * * {dow}"
        return cron, label

    async def schedule_daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /schedule-daily [HH:MM] <task>

        Create a daily reminder. HH:MM is optional (defaults to 09:00).
        Example: /schedule-daily 08:30 review goals
        """
        if await _reject_unauthorized(update):
            return

        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if automation_store is None or _sched is None:
            await update.message.reply_text(
                "Automation not available — scheduler not configured."
            )
            return

        cron, label = _parse_schedule_args(context.args or [])
        if not label:
            await update.message.reply_text(
                "Usage: /schedule_daily [HH:MM] <task>\n"
                "Example: /schedule_daily 08:30 review my goals"
            )
            return

        user_id = update.effective_user.id
        try:
            automation_id = await automation_store.add(user_id, label, cron)
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to save automation: {e}")
            return

        _sched.add_automation(automation_id, user_id, label, cron)
        # Display human-friendly time from cron
        minute, hour = cron.split()[0], cron.split()[1]
        time_str = f"{int(hour):02d}:{int(minute):02d}"
        await update.message.reply_text(
            f"✅ Daily reminder set (ID {automation_id})\n"
            f"*{label}*\nFires every day at {time_str}.",
            parse_mode="Markdown",
        )

    async def schedule_weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /schedule-weekly [day] [HH:MM] <task>

        Create a weekly reminder. Day defaults to Monday, time to 09:00.
        Example: /schedule-weekly fri 09:00 review week
        """
        if await _reject_unauthorized(update):
            return

        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if automation_store is None or _sched is None:
            await update.message.reply_text(
                "Automation not available — scheduler not configured."
            )
            return

        cron, label = _parse_schedule_args(context.args or [], default_dow="1")
        if not label:
            await update.message.reply_text(
                "Usage: /schedule_weekly [day] [HH:MM] <task>\n"
                "Example: /schedule_weekly fri 09:00 weekly review"
            )
            return

        user_id = update.effective_user.id
        try:
            automation_id = await automation_store.add(user_id, label, cron)
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to save automation: {e}")
            return

        _sched.add_automation(automation_id, user_id, label, cron)
        _DOW_NAMES = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "*": "every day"}
        minute, hour, _, _, dow = cron.split()
        time_str = f"{int(hour):02d}:{int(minute):02d}"
        day_str = _DOW_NAMES.get(dow, dow)
        await update.message.reply_text(
            f"✅ Weekly reminder set (ID {automation_id})\n"
            f"*{label}*\nFires every {day_str} at {time_str}.",
            parse_mode="Markdown",
        )

    async def list_automations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /list-automations — show all scheduled reminders with their IDs.
        """
        if await _reject_unauthorized(update):
            return

        if automation_store is None:
            await update.message.reply_text("Automation not available.")
            return

        user_id = update.effective_user.id
        rows = await automation_store.get_all(user_id)

        if not rows:
            await update.message.reply_text(
                "No automations scheduled.\n"
                "Use /schedule_daily or /schedule_weekly to create one."
            )
            return

        _DOW_NAMES = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "*": "daily"}
        lines = ["⏰ *Scheduled reminders:*\n"]
        for row in rows:
            cron_parts = row["cron"].split()
            minute, hour, _, _, dow = cron_parts
            time_str = f"{int(hour):02d}:{int(minute):02d}"
            freq = "daily" if dow == "*" else f"every {_DOW_NAMES.get(dow, dow)}"
            last = row["last_run_at"] or "never"
            lines.append(f"*[{row['id']}]* {row['label']}\n  ↳ {freq} at {time_str} | last run: {last}")

        lines.append("\nUse /unschedule <id> to remove one.")  # unschedule has no dash
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def unschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /unschedule <id> — remove a scheduled reminder by its ID.
        """
        if await _reject_unauthorized(update):
            return

        _sched = (scheduler_ref or {}).get("proactive_scheduler") or proactive_scheduler
        if automation_store is None or _sched is None:
            await update.message.reply_text("Automation not available.")
            return

        args = context.args or []
        if not args or not args[0].isdigit():
            await update.message.reply_text(
                "Usage: /unschedule <id>\nUse /list_automations to see IDs."
            )
            return

        automation_id = int(args[0])
        user_id = update.effective_user.id

        removed = await automation_store.remove(user_id, automation_id)
        if not removed:
            await update.message.reply_text(
                f"❌ No automation with ID {automation_id} found (or it doesn't belong to you)."
            )
            return

        _sched.remove_automation(automation_id)
        await update.message.reply_text(f"✅ Reminder {automation_id} removed.")

    async def breakdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /breakdown <task> — break a task into 5 clear, actionable steps.

        Uses Claude to decompose the task and returns a numbered plan.
        """
        if await _reject_unauthorized(update):
            return

        task = " ".join(context.args or []).strip()
        if not task:
            await update.message.reply_text(
                "Usage: /breakdown <task>\n"
                "Example: /breakdown organise my Projects folder"
            )
            return

        if claude_client is None:
            await update.message.reply_text("Breakdown unavailable — no Claude client.")
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Breaking it down…")

        # Inject user context (goals/facts) if available
        user_id = update.effective_user.id
        context_block = ""
        if memory_injector is not None:
            try:
                full_prompt = await memory_injector.build_system_prompt(user_id, task, "")
                if "<memory>" in full_prompt:
                    start = full_prompt.index("<memory>")
                    end = full_prompt.index("</memory>") + len("</memory>")
                    context_block = full_prompt[start:end]
            except Exception as exc:
                logger.debug("Breakdown memory injection failed: %s", exc)

        system = (
            "You are an ADHD-friendly task coach. When given a task, break it down into "
            "exactly 5 clear, concrete, actionable steps. Each step should be completable "
            "in under 30 minutes. Number them 1–5. Be specific and encouraging. "
            "After the steps, add one brief motivational sentence."
        )
        if context_block:
            system += f"\n\nUser context:\n{context_block}"

        try:
            response = await claude_client.complete(
                messages=[{"role": "user", "content": f"Break down this task: {task}"}],
                system=system,
                max_tokens=600,
            )
        except Exception as exc:
            logger.error("Breakdown error for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not break down task: {exc}")
            return

        plan_text = response if isinstance(response, str) else str(response)
        await sent.edit_text(
            f"📋 *Breaking down:* _{task}_\n\n{plan_text}",
            parse_mode="Markdown",
        )

    # ------------------------------------------------------------------ #
    # Phase 6: Analytics commands                                           #
    # ------------------------------------------------------------------ #

    async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/stats [period] — conversation usage statistics."""
        if await _reject_unauthorized(update):
            return
        if conversation_analyzer is None:
            await update.message.reply_text("Analytics not available.")
            return

        args = context.args or []
        period = args[0].lower() if args else "30d"
        valid_periods = {"7d", "30d", "90d", "all", "month"}
        if period not in valid_periods and not (period.endswith("d") and period[:-1].isdigit()):
            await update.message.reply_text(
                "Usage: /stats [period]\nValid periods: 7d, 30d (default), 90d, all"
            )
            return

        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Calculating stats…")
        try:
            stats = await conversation_analyzer.get_stats(user_id, period)
            msg = conversation_analyzer.format_stats_message(stats)
            await sent.edit_text(msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Stats command failed for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not calculate stats: {exc}")

    async def goal_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/goal-status — goal tracking dashboard with age and staleness info."""
        if await _reject_unauthorized(update):
            return
        if conversation_analyzer is None:
            await update.message.reply_text("Analytics not available.")
            return

        from datetime import datetime, timedelta, timezone
        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        sent = await update.message.reply_text("Loading goal status…")
        try:
            active = await conversation_analyzer.get_active_goals_with_age(user_id)
            since = datetime.now(timezone.utc) - timedelta(days=30)
            completed = await conversation_analyzer.get_completed_goals_since(user_id, since)
            msg = conversation_analyzer.format_goal_status_message(active, completed)
            await sent.edit_text(msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Goal status command failed for user %d: %s", user_id, exc)
            await sent.edit_text(f"❌ Could not load goal status: {exc}")

    async def retrospective_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/retrospective — generate a monthly retrospective using Claude (fire-and-forget)."""
        if await _reject_unauthorized(update):
            return
        if conversation_analyzer is None:
            await update.message.reply_text("Analytics not available.")
            return
        if claude_client is None:
            await update.message.reply_text("Claude client not available.")
            return

        user_id = update.effective_user.id
        await update.message.reply_text("Started — I'll message you when done 🔄")

        async def _run_retrospective() -> str:
            return await conversation_analyzer.generate_retrospective(
                user_id, "month", claude_client
            )

        runner = BackgroundTaskRunner(context.bot, update.message.chat_id)
        asyncio.create_task(runner.run(_run_retrospective(), label="retrospective"))

    # ------------------------------------------------------------------ #
    # Message handler                                                       #
    # ------------------------------------------------------------------ #

    async def _ensure_user(user: object) -> None:
        """Upsert the Telegram user into the users table (satisfies FK constraint)."""
        if db is None:
            return
        try:
            await db.upsert_user(
                user.id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
            )
        except Exception as exc:
            logger.warning("upsert_user failed: %s", exc)

    async def _stream_with_tools_path(
        user_id: int,
        text: str,
        messages: list[dict],
        system_prompt: str,
        session_key: str,
        sent,  # Initial Telegram message to stream into
    ) -> None:
        """
        Tool-aware streaming path using native Anthropic function calling.

        Streams Claude's response, handling tool calls autonomously. Text chunks
        are streamed live to Telegram. Tool calls are executed and fed back.
        Tool turns (multi-block) are serialised and stored in conversation history.

        The final accumulated text (all text chunks across all iterations) is
        stored as the assistant turn. Tool turns are stored separately with the
        _TOOL_TURN_PREFIX sentinel.
        """
        current_display: list[str] = []    # text currently shown in Telegram message
        tool_turns: list[tuple[list[dict], list[dict]]] = []  # (assistant_blocks, result_blocks)

        in_tool_turn = False  # True between ToolStatusChunk and ToolTurnComplete;
                              # TextChunks arriving in this window are suppressed
        last_edit_len = 0
        rotator = MessageRotator(sent, user_id)
        rotator_stopped = False

        async def _flush_display(final: bool = False) -> None:
            """Push accumulated display text to Telegram message."""
            nonlocal last_edit_len
            full = "".join(current_display)
            suffix = "" if final else " …"
            candidate = full + suffix

            if not candidate.strip():
                return  # nothing to show — avoid blank-message errors

            # Only edit if there's meaningful new content
            if len(full) > last_edit_len + 50 or final:
                truncated = candidate[:4000]
                try:
                    await sent.edit_text(truncated, parse_mode="Markdown")
                    last_edit_len = len(full)
                except Exception as _md_err:
                    # Partial stream may have unbalanced markdown — fall back to plain
                    try:
                        await sent.edit_text(truncated)
                        last_edit_len = len(full)
                    except Exception:
                        pass  # Skip failed edits (no-change, flood control, etc.)

        try:
            rotator.start()
            async for event in claude_client.stream_with_tools(
                messages=messages,
                tool_registry=tool_registry,
                user_id=user_id,
                system=system_prompt,
            ):
                if not rotator_stopped:
                    await rotator.stop()
                    rotator_stopped = True
                if session_manager.is_cancelled(user_id):
                    shown = "".join(current_display)
                    try:
                        await sent.edit_text(
                            (shown + "\n\n_[cancelled]_").strip(),
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
                    return

                if isinstance(event, TextChunk):
                    if in_tool_turn:
                        # Suppress internal monologue emitted while a tool is
                        # executing (between ToolStatusChunk and ToolTurnComplete).
                        logger.debug(
                            "Suppressing in-tool TextChunk (%d chars) for user %d",
                            len(event.text), user_id,
                        )
                    else:
                        # Normal path: live-stream text to Telegram.
                        # Covers pure-text responses, pre-tool preamble, and
                        # final response after all tool turns complete.
                        current_display.append(event.text)
                        if len("".join(current_display)) - last_edit_len >= 200:
                            await _flush_display()

                elif isinstance(event, ToolStatusChunk):
                    in_tool_turn = True
                    # Show a clean tool-status indicator (direct edit, no append)
                    try:
                        await sent.edit_text(
                            f"_⚙️ Using {event.tool_name}…_",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass

                elif isinstance(event, ToolResultChunk):
                    pass  # tool finished; ToolTurnComplete follows

                elif isinstance(event, ToolTurnComplete):
                    in_tool_turn = False
                    # Store the tool turn for conversation history
                    tool_turns.append(
                        (event.assistant_blocks, event.tool_result_blocks)
                    )
                    # Reset display for the next iteration's text (final response
                    # or further tool preamble)
                    current_display = []
                    last_edit_len = 0

        except Exception as exc:
            if not rotator_stopped:
                await rotator.stop()
            logger.error("stream_with_tools error for user %d: %s", user_id, exc)
            await sent.edit_text(f"Sorry, something went wrong: {exc}")
            return

        # Final flush — show complete response
        await _flush_display(final=True)

        # Persist conversation history
        # 1. Save tool turns (multi-block) with sentinel prefix
        for assistant_blocks, result_blocks in tool_turns:
            # Assistant turn with tool_use blocks
            asst_serialised = _TOOL_TURN_PREFIX + json.dumps(assistant_blocks)
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="assistant", content=asst_serialised, model_used="claude:sonnet"),
            )
            # User turn with tool_result blocks
            usr_serialised = _TOOL_TURN_PREFIX + json.dumps(result_blocks)
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="user", content=usr_serialised),
            )

        # 2. Save final assistant text turn (if any)
        # current_display is reset on every ToolTurnComplete, so it contains only
        # the final iteration's text — pre-tool preambles from intermediate iterations
        # are already stored inside each tool_turn's assistant_blocks.
        final_text = "".join(current_display).strip()
        if final_text:
            await conv_store.append_turn(
                user_id, session_key,
                ConversationTurn(role="assistant", content=final_text, model_used="claude:sonnet"),
            )

    async def _process_text_input(
        user_id: int,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Process text input (from message or transcribed voice) and generate response."""
        if not text.strip():
            return

        # 1. RATE LIMITING CHECK
        allowed, rate_limit_reason = _rate_limiter.is_allowed(user_id)
        if not allowed:
            await update.message.reply_text(f"⏱️ {rate_limit_reason}")
            return

        # 2. INPUT VALIDATION
        valid, validation_reason = validate_message_input(text)
        if not valid:
            await update.message.reply_text(f"❌ {validation_reason}")
            return

        # 3. TASK TIMEOUT CHECK
        if user_id in _task_start_times:
            elapsed = time.time() - _task_start_times[user_id]
            if elapsed > TASK_TIMEOUT_SECONDS:
                _task_start_times.pop(user_id, None)
                session_manager.request_cancel(user_id)
                await update.message.reply_text(
                    "⏰ Previous task exceeded 2-hour limit and was cancelled. Starting fresh."
                )

        # 4. RECORD TASK START TIME
        _task_start_times[user_id] = time.time()

        # Ensure user row exists before any FK-dependent writes (facts, goals)
        await _ensure_user(update.effective_user)
        # Acquire per-user lock
        async with session_manager.get_lock(user_id):
            session_manager.clear_cancel(user_id)
            session_key = SessionManager.get_session_key(user_id)

            # 5a. INTERCEPT PENDING GMAIL ARCHIVE CONFIRMATION
            if user_id in _pending_archive:
                message_ids = _pending_archive.pop(user_id)
                if text.strip().lower() == "yes":
                    if google_gmail is not None:
                        try:
                            n = await google_gmail.archive_messages(message_ids)
                            await update.message.reply_text(f"✅ Archived {n} email(s).")
                        except Exception as e:
                            await update.message.reply_text(f"❌ Archive failed: {e}")
                    else:
                        await update.message.reply_text("❌ Gmail not configured.")
                else:
                    await update.message.reply_text("Archive cancelled.")
                _task_start_times.pop(user_id, None)
                return

            # 5b. INTERCEPT PENDING WRITE (inside lock to prevent races between messages)
            if user_id in _pending_writes:
                pending_path = _pending_writes.pop(user_id)
                sanitized, err = sanitize_file_path(pending_path, _ALLOWED_BASE_DIRS)
                if err or sanitized is None:
                    await update.message.reply_text(f"❌ Write cancelled: {err}")
                else:
                    try:
                        backup_msg = ""
                        if os.path.exists(sanitized):
                            backup_path = sanitized + ".bak"
                            shutil.copy2(sanitized, backup_path)
                            backup_msg = f"\n_(Backup saved as `{backup_path}`)_"
                        with open(sanitized, "w", encoding="utf-8") as f:
                            f.write(text)
                        await update.message.reply_text(
                            f"✅ Wrote {len(text)} characters to `{sanitized}`{backup_msg}",
                            parse_mode="Markdown",
                        )
                    except Exception as e:
                        await update.message.reply_text(f"❌ Failed to write file: {e}")
                _task_start_times.pop(user_id, None)
                return

            # Show typing indicator
            await update.message.chat.send_action(ChatAction.TYPING)

            # Build messages list from recent history (tool-turn-aware)
            recent = await conv_store.get_recent_turns(user_id, session_key, limit=20)
            messages = [_build_message_from_turn(t) for t in recent]
            # Strip orphaned tool-turn fragments from the start of history.
            # get_recent_turns slices the last N turns blindly, so the cutoff
            # can land inside a tool_use/tool_result pair leaving a user
            # tool_result with no matching assistant tool_use — causing a 400.
            # Drop everything before the first plain-string user message.
            while messages:
                first = messages[0]
                if first["role"] == "user" and isinstance(first["content"], str):
                    break
                messages.pop(0)
            # Trim history to stay within TPM budget (large tool results from
            # Gmail / calendar ops can push input tokens well over the limit).
            messages = _trim_messages_to_budget(messages)
            messages.append({"role": "user", "content": text})

            # Save the user turn immediately
            user_turn = ConversationTurn(role="user", content=text)
            await conv_store.append_turn(user_id, session_key, user_turn)

            # Build system prompt with memory injection
            system_prompt = settings.soul_md
            if memory_injector is not None:
                try:
                    system_prompt = await memory_injector.build_system_prompt(
                        user_id, text, settings.soul_md
                    )
                    # Sanitize injected memory to prevent prompt injection attacks
                    system_prompt = sanitize_memory_injection(system_prompt)
                except Exception as e:
                    logger.warning("Memory injection failed, using base prompt: %s", e)

            # Conditional trigger hints (Phase 5 ADHD body-double)
            text_lower = text.lower()
            _SHOPPING_KEYWORDS = {"shopping", "grocery", "groceries", "supermarket", "shops"}
            _DEADLINE_KEYWORDS = {"deadline", "due date", "due by", "by friday", "by monday",
                                  "by tomorrow", "by next week", "must finish", "need to finish"}
            if any(kw in text_lower for kw in _SHOPPING_KEYWORDS):
                try:
                    grocery_file = settings.grocery_list_file
                    if os.path.exists(grocery_file):
                        with open(grocery_file) as _gf:
                            items = [ln.strip() for ln in _gf if ln.strip()]
                        if items:
                            item_list = "\n".join(f"- {i}" for i in items)
                            system_prompt += (
                                f"\n\n<hint>The user mentioned shopping. "
                                f"Their current grocery list:\n{item_list}\n"
                                f"Offer to reference or update it if helpful.</hint>"
                            )
                except Exception:
                    pass
            if any(kw in text_lower for kw in _DEADLINE_KEYWORDS):
                system_prompt += (
                    "\n\n<hint>The user may be mentioning a deadline or time-sensitive task. "
                    "If relevant, offer to create a calendar event using /schedule.</hint>"
                )

            # Send placeholder message to stream into
            sent = await update.message.reply_text(_get_working_msg())

            # ---------------------------------------------------------------- #
            # Path A: Native tool use (preferred when tool_registry available)  #
            # ---------------------------------------------------------------- #
            if tool_registry is not None and claude_client is not None:
                await _stream_with_tools_path(
                    user_id=user_id,
                    text=text,
                    messages=messages,
                    system_prompt=system_prompt,
                    session_key=session_key,
                    sent=sent,
                )
                # Clear task timer on completion (path A)
                _task_start_times.pop(user_id, None)
                # Background: extract facts and goals from the user's message
                if fact_extractor is not None and fact_store is not None:
                    asyncio.create_task(
                        extract_and_store_facts(user_id, text, fact_extractor, fact_store)
                    )
                if goal_extractor is not None and goal_store is not None:
                    asyncio.create_task(
                        extract_and_store_goals(user_id, text, goal_extractor, goal_store)
                    )
                return

            # ---------------------------------------------------------------- #
            # Path B: Router fallback (no tool_registry)                        #
            # ---------------------------------------------------------------- #
            rotator = MessageRotator(sent, user_id)
            rotator.start()
            rotator_stopped = False

            async def wrapper_stream():
                nonlocal rotator_stopped
                async for chunk in router.stream(text, messages, user_id, system=system_prompt):
                    if not rotator_stopped:
                        await rotator.stop()
                        rotator_stopped = True
                    yield chunk

            try:
                response_text = await stream_to_telegram(
                    chunks=wrapper_stream(),
                    initial_message=sent,
                    session_manager=session_manager,
                    user_id=user_id,
                )
            except ServiceUnavailableError as e:
                _task_start_times.pop(user_id, None)
                await sent.edit_text(
                    f"❌ Service unavailable: {e}\n\nFallback: Check /status or try again in a moment."
                )
                return
            except Exception as e:
                _task_start_times.pop(user_id, None)
                logger.error("Error processing message for user %d: %s", user_id, e)
                await sent.edit_text(f"❌ Sorry, something went wrong: {e}")
                return
            finally:
                if not rotator_stopped:
                    await rotator.stop()

            # Save assistant turn
            model_name = router.last_model
            assistant_turn = ConversationTurn(role="assistant", content=response_text, model_used=model_name)
            await conv_store.append_turn(user_id, session_key, assistant_turn)

            # Clear task timer on success
            _task_start_times.pop(user_id, None)

            # Background: extract facts and goals from the user's message
            if fact_extractor is not None and fact_store is not None:
                asyncio.create_task(
                    extract_and_store_facts(user_id, text, fact_extractor, fact_store)
                )
            if goal_extractor is not None and goal_store is not None:
                asyncio.create_task(
                    extract_and_store_goals(user_id, text, goal_extractor, goal_store)
                )

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await _reject_unauthorized(update):
            return

        user = update.effective_user
        user_id = user.id
        text = update.message.text or ""

        await _process_text_input(user_id, text, update, context)

    async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Transcribe voice messages and process as text."""
        if await _reject_unauthorized(update):
            return

        if voice_transcriber is None:
            await update.message.reply_text(
                "Voice transcription not available. Install faster-whisper."
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        voice_file = await update.message.voice.get_file()

        transcript = await voice_transcriber.transcribe(voice_file)
        if not transcript:
            await update.message.reply_text("[Could not transcribe voice message]")
            return

        await update.message.reply_text(f"🎙 _{transcript}_", parse_mode="Markdown")

        # Process the transcribed text directly
        user_id = update.effective_user.id
        await _process_text_input(user_id, transcript, update, context)

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process photo messages — download, encode to base64, analyse with Claude vision."""
        if await _reject_unauthorized(update):
            return

        if claude_client is None:
            await update.message.reply_text("Image analysis not available (Claude not configured).")
            return

        user_id = update.effective_user.id

        # Rate limiting
        allowed, rate_limit_reason = _rate_limiter.is_allowed(user_id)
        if not allowed:
            await update.message.reply_text(f"⏱️ {rate_limit_reason}")
            return

        # Task timeout check
        if user_id in _task_start_times:
            elapsed = time.time() - _task_start_times[user_id]
            if elapsed > TASK_TIMEOUT_SECONDS:
                _task_start_times.pop(user_id, None)
                session_manager.request_cancel(user_id)
                await update.message.reply_text(
                    "⏰ Previous task exceeded 2-hour limit and was cancelled. Starting fresh."
                )
        _task_start_times[user_id] = time.time()

        await update.message.chat.send_action(ChatAction.TYPING)

        # Download highest-resolution version of the photo
        photo = update.message.photo[-1]
        caption = update.message.caption or ""
        user_text = caption if caption else "What is this image?"

        try:
            photo_file = await photo.get_file()
            bio = io.BytesIO()
            await photo_file.download_to_memory(bio)
            image_bytes = bio.getvalue()
        except Exception as exc:
            logger.error("Failed to download photo for user %d: %s", user_id, exc)
            await update.message.reply_text("❌ Could not download photo.")
            _task_start_times.pop(user_id, None)
            return

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        await _ensure_user(update.effective_user)
        async with session_manager.get_lock(user_id):
            session_manager.clear_cancel(user_id)
            session_key = SessionManager.get_session_key(user_id)

            # Build history from conv_store
            recent = await conv_store.get_recent_turns(user_id, session_key, limit=20)
            messages = [_build_message_from_turn(t) for t in recent]
            # Strip orphaned tool-turn fragments from the start of history
            while messages:
                first = messages[0]
                if first["role"] == "user" and isinstance(first["content"], str):
                    break
                messages.pop(0)
            messages = _trim_messages_to_budget(messages)

            # Append the image message as a multi-block content list
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            })

            # Save user turn as text-only — do NOT store image bytes in history
            history_text = f"[photo] {caption}" if caption else "[photo]"
            user_turn = ConversationTurn(role="user", content=history_text)
            await conv_store.append_turn(user_id, session_key, user_turn)

            # Build system prompt with memory injection
            system_prompt = settings.soul_md
            if memory_injector is not None:
                try:
                    system_prompt = await memory_injector.build_system_prompt(
                        user_id, user_text, settings.soul_md
                    )
                    system_prompt = sanitize_memory_injection(system_prompt)
                except Exception as e:
                    logger.warning("Memory injection failed, using base prompt: %s", e)

            # Send placeholder message to stream into
            sent = await update.message.reply_text("…")

            if tool_registry is not None and claude_client is not None:
                await _stream_with_tools_path(
                    user_id=user_id,
                    text=user_text,
                    messages=messages,
                    system_prompt=system_prompt,
                    session_key=session_key,
                    sent=sent,
                )
            else:
                # Path B fallback: router (won't use image block but won't crash)
                try:
                    await stream_to_telegram(
                        chunks=router.stream(user_text, messages, user_id, system=system_prompt),
                        initial_message=sent,
                        session_manager=session_manager,
                        user_id=user_id,
                    )
                except Exception as exc:
                    logger.error("Error processing photo for user %d: %s", user_id, exc)
                    await sent.edit_text(f"❌ Sorry, something went wrong: {exc}")

            _task_start_times.pop(user_id, None)

    return {
        "start": start_command,
        "help": help_command,
        "cancel": cancel_command,
        "status": status_command,
        "compact": compact_command,
        "setmychat": setmychat_command,
        "briefing": briefing_command,
        "goals": goals_command,
        "read": read_command,
        "write": write_command,
        "ls": ls_command,
        "find": find_command,
        "set_project": set_project_command,
        "project_status": project_status_command,
        "scan_downloads": scan_downloads_command,
        "organize": organize_command,
        "clean": clean_command,
        "calendar": calendar_command,
        "calendar-today": calendar_today_command,
        "schedule": schedule_command,
        "gmail-unread": gmail_unread_command,
        "gmail-unread-summary": gmail_unread_summary_command,
        "gmail-classify": gmail_classify_command,
        "gmail-search": gmail_search_command,
        "gmail-read": gmail_read_command,
        "gmail-labels": gmail_labels_command,
        "gdoc": gdoc_command,
        "gdoc-append": gdoc_append_command,
        "contacts": contacts_command,
        "contacts-birthday": contacts_birthday_command,
        "contacts-details": contacts_details_command,
        "contacts-note": contacts_note_command,
        "contacts-prune": contacts_prune_command,
        "search": search_command,
        "research": research_command,
        "save-url": save_url_command,
        "bookmarks": bookmarks_command,
        "grocery-list": grocery_list_command,
        "price-check": price_check_command,
        "delete_conversation": delete_conversation_command,
        "logs": logs_command,
        "board": board_command,
        "schedule-daily": schedule_daily_command,
        "schedule-weekly": schedule_weekly_command,
        "list-automations": list_automations_command,
        "unschedule": unschedule_command,
        "breakdown": breakdown_command,
        "stats": stats_command,
        "goal-status": goal_status_command,
        "retrospective": retrospective_command,
        "message": handle_message,
        "voice": handle_voice,
        "photo": handle_photo,
    }
