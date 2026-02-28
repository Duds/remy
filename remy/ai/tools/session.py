"""Session, privacy, and special tool executors."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import ToolRegistry

logger = logging.getLogger(__name__)


async def exec_compact_conversation(registry: ToolRegistry, user_id: int) -> str:
    """Compact the conversation history."""
    return (
        "Conversation compaction requires access to the conversation store and Claude client, "
        "which are not available in the tool context. "
        "Please use the /compact command directly to summarise and compress the conversation."
    )


async def exec_delete_conversation(registry: ToolRegistry, user_id: int) -> str:
    """Delete the conversation history."""
    return (
        "Conversation deletion requires access to the conversation store, "
        "which is not available in the tool context. "
        "Please use the /delete_conversation command directly to clear history."
    )


async def exec_set_proactive_chat(
    registry: ToolRegistry, user_id: int, chat_id: int | None = None
) -> str:
    """Set the current chat for proactive messages."""
    if chat_id is None:
        return (
            "Setting the proactive chat requires access to the Telegram chat context, "
            "which is not available in the tool context. "
            "Please use the /setmychat command directly to set this chat for briefings."
        )

    from ...config import settings

    path = settings.primary_chat_file
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w") as f:
            f.write(str(chat_id))
        return f"✅ This chat is now set for proactive messages (ID: {chat_id})"
    except OSError as e:
        return f"❌ Could not save chat setting: {e}"


async def exec_trigger_reindex(registry: ToolRegistry) -> str:
    """Trigger a file reindex."""
    sched = registry._proactive_scheduler
    if sched is None:
        return "Scheduler not available."

    try:
        stats = await sched.run_file_reindex_now()
    except Exception as e:
        return f"Reindex failed: {e}"

    if stats.get("status") == "error":
        return f"❌ {stats.get('message', 'Reindex failed')}"
    if stats.get("status") == "disabled":
        return "File indexing is disabled in configuration."

    return (
        f"✅ File reindex complete:\n"
        f"  Files indexed: {stats.get('files_indexed', 0)}\n"
        f"  Chunks created: {stats.get('chunks_created', 0)}\n"
        f"  Files removed: {stats.get('files_removed', 0)}\n"
        f"  Files skipped: {stats.get('files_skipped', 0)}\n"
        f"  Errors: {stats.get('errors', 0)}"
    )


async def exec_start_privacy_audit(registry: ToolRegistry) -> str:
    """Start a privacy audit wizard."""
    return (
        "🔒 Privacy Audit\n\n"
        "I can help you check your digital footprint. To begin, I'll need you to share:\n\n"
        "1. Your full name (as it appears publicly)\n"
        "2. Any email addresses you want to check\n"
        "3. Any usernames you use on social media or forums\n\n"
        "I'll search for:\n"
        "• Data broker presence (Whitepages, Spokeo, etc.)\n"
        "• Breach exposure (Have I Been Pwned style checks)\n"
        "• Public social media profiles\n\n"
        "What would you like me to check first? Share a name, email, or username."
    )


async def exec_end_session(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """End the current conversation session and optionally set a reminder."""
    reminder_minutes = inp.get("reminder_minutes")
    reminder_text = inp.get("reminder_text", "").strip()

    result_parts = ["Session ended."]

    if reminder_minutes and registry._automation_store:
        try:
            from .automations import exec_set_one_time_reminder

            reminder_inp = {
                "minutes": reminder_minutes,
                "message": reminder_text or "Follow up on our last conversation",
            }
            reminder_result = await exec_set_one_time_reminder(registry, reminder_inp, user_id)
            result_parts.append(reminder_result)
        except Exception as e:
            result_parts.append(f"Could not set reminder: {e}")

    return "\n\n".join(result_parts)


async def exec_help(registry: ToolRegistry, inp: dict, user_id: int) -> str:
    """Show available tools and their descriptions."""
    from .schemas import TOOL_SCHEMAS

    category = inp.get("category", "").strip().lower()

    _CATEGORY_MAP = {
        "time": ["get_current_time"],
        "memory": [
            "get_logs",
            "get_goals",
            "get_facts",
            "run_board",
            "check_status",
            "manage_memory",
            "manage_goal",
            "get_memory_summary",
        ],
        "calendar": ["calendar_events", "create_calendar_event"],
        "email": [
            "read_emails",
            "search_gmail",
            "read_email",
            "list_gmail_labels",
            "label_emails",
            "create_gmail_label",
            "create_email_draft",
            "classify_promotional_emails",
        ],
        "contacts": [
            "search_contacts",
            "upcoming_birthdays",
            "get_contact_details",
            "update_contact_note",
            "find_sparse_contacts",
        ],
        "files": [
            "read_file",
            "list_directory",
            "write_file",
            "append_file",
            "find_files",
            "scan_downloads",
            "organize_directory",
            "clean_directory",
            "search_files",
            "index_status",
        ],
        "web": ["web_search", "price_check"],
        "automations": [
            "schedule_reminder",
            "list_reminders",
            "remove_reminder",
            "set_one_time_reminder",
            "breakdown_task",
            "grocery_list",
        ],
        "plans": [
            "create_plan",
            "get_plan",
            "list_plans",
            "update_plan_step",
            "update_plan_status",
        ],
        "analytics": [
            "get_stats",
            "get_goal_status",
            "generate_retrospective",
            "consolidate_memory",
            "list_background_jobs",
            "get_costs",
        ],
        "session": ["end_session", "help"],
    }

    if category and category in _CATEGORY_MAP:
        tool_names = set(_CATEGORY_MAP[category])
        filtered = [t for t in TOOL_SCHEMAS if t["name"] in tool_names]
        lines = [f"**{category.title()} Tools** ({len(filtered)}):\n"]
        for tool in filtered:
            lines.append(f"• **{tool['name']}**: {tool['description'][:100]}")
        return "\n".join(lines)

    lines = ["**Available Tool Categories:**\n"]
    for cat, tools in _CATEGORY_MAP.items():
        lines.append(f"• **{cat}** ({len(tools)} tools)")

    lines.append("\n\nUse `help(category='...')` to see tools in a specific category.")
    lines.append(f"\nTotal tools available: {len(TOOL_SCHEMAS)}")

    return "\n".join(lines)
